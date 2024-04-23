import torch
from .common import standardize, recorrelate_colors, optimization_step
from tqdm import tqdm

def fft_2d_freq(width, height):
    # calculate the 2D frequency grid for FFT
    freq_y = torch.fft.fftfreq(height).unsqueeze(1)

    cut_off = int(width % 2 == 1)
    freq_x = torch.fft.fftfreq(width)[:width//2+1+cut_off]

    return torch.sqrt(freq_x**2 + freq_y**2)

def get_fft_scale(width, height, decay_power=1.0):
    # generate the FFT scale based on the image size and decay power
    frequencies = fft_2d_freq(width, height)

    fft_scale = 1.0 / torch.maximum(frequencies, torch.tensor(1.0 / max(width, height))) ** decay_power
    fft_scale = fft_scale * torch.sqrt(torch.tensor(width * height).float())

    return fft_scale.to(torch.complex64)

def init_olah_buffer(width, height, std=1.0):
    # initialize the Olah buffer with a random spectrum
    spectrum_shape = (3, width, height // 2 + 1)
    random_spectrum = torch.complex(torch.randn(spectrum_shape) * std, torch.randn(spectrum_shape) * std)
    return random_spectrum

def fourier_preconditionner(spectrum, spectrum_scaler, values_range):
    # precondition the Fourier spectrum and convert it to spatial domain
    assert spectrum.shape[0] == 3

    spectrum = standardize(spectrum)
    spectrum = spectrum * spectrum_scaler

    spatial_image = torch.fft.irfft2(spectrum)
    spatial_image = standardize(spatial_image)
    color_recorrelated_image = recorrelate_colors(spatial_image)

    image = torch.sigmoid(color_recorrelated_image) * (values_range[1] - values_range[0]) + values_range[0]
    return image

def fourier(objective_function, decay_power=1.5, total_steps=1000, learning_rate=1.0, image_size=1280, model_input_size=224,
         noise=0.05, values_range=(-2.5, 2.5), crops_per_iteration=6, box_size=(0.20, 0.25), device='cuda'):
    # perform the Olah optimization process
    assert values_range[1] >= values_range[0]
    assert box_size[1] >= box_size[0]

    spectrum = init_olah_buffer(image_size, image_size, std=1.0)
    spectrum_scaler = get_fft_scale(image_size, image_size, decay_power)

    spectrum = spectrum.to(device)
    spectrum.requires_grad = True
    spectrum_scaler = spectrum_scaler.to(device)

    optimizer = torch.optim.NAdam([spectrum], lr=learning_rate)
    transparency_accumulator = torch.zeros((3, image_size, image_size)).to(device)

    for step in tqdm(range(total_steps)):
        optimizer.zero_grad()

        image = fourier_preconditionner(spectrum, spectrum_scaler, values_range)
        loss, img = optimization_step(objective_function, image, box_size, noise, crops_per_iteration, model_input_size)
        loss.backward()
        transparency_accumulator += torch.abs(img.grad)
        optimizer.step()

    final_image = fourier_preconditionner(spectrum, spectrum_scaler, values_range)
    return final_image, transparency_accumulator
