import math

import torch
import torch.nn.functional as F

try:
    import torchaudio.functional as torchaudio_functional
except Exception:
    torchaudio_functional = None


AUDIO_SPEED_METHODS = ["preserve_pitch", "resample"]


def ensure_audio(audio, node_name, input_name):
    if not isinstance(audio, dict):
        raise TypeError(
            f"{node_name}: expected '{input_name}' to be an AUDIO dict, got {type(audio).__name__}."
        )
    if "waveform" not in audio:
        raise ValueError(f"{node_name}: expected '{input_name}' to include a 'waveform' tensor.")
    if "sample_rate" not in audio:
        raise ValueError(f"{node_name}: expected '{input_name}' to include a 'sample_rate' value.")

    waveform = audio["waveform"]
    if not isinstance(waveform, torch.Tensor):
        raise TypeError(
            f"{node_name}: expected '{input_name}.waveform' to be a torch.Tensor, got {type(waveform).__name__}."
        )
    if waveform.ndim != 3:
        raise ValueError(
            f"{node_name}: expected '{input_name}.waveform' to have shape [B, C, T], got {tuple(waveform.shape)}."
        )
    if waveform.shape[0] < 1 or waveform.shape[1] < 1:
        raise ValueError(f"{node_name}: expected '{input_name}.waveform' to contain at least one audio channel.")
    if waveform.shape[-1] < 1:
        raise ValueError(f"{node_name}: expected '{input_name}.waveform' to contain at least one sample.")

    try:
        sample_rate = int(audio["sample_rate"])
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{node_name}: expected '{input_name}.sample_rate' to be a positive integer.") from exc
    if sample_rate <= 0:
        raise ValueError(f"{node_name}: expected '{input_name}.sample_rate' to be a positive integer.")

    if not waveform.dtype.is_floating_point:
        waveform = waveform.float()

    return waveform, sample_rate


def target_sample_count(sample_count, speed):
    return max(1, int(round(sample_count / speed)))


def resample_speed(waveform, speed):
    sample_count = waveform.shape[-1]
    target_count = target_sample_count(sample_count, speed)
    if target_count == sample_count:
        return waveform.clone()
    if sample_count == 1:
        return waveform.expand(*waveform.shape[:-1], target_count).clone()

    batch_shape = waveform.shape[:-1]
    flat = waveform.reshape(-1, 1, sample_count)
    stretched = F.interpolate(flat, size=target_count, mode="linear", align_corners=False)
    return stretched.reshape(*batch_shape, target_count)


def choose_fft_size(sample_count):
    if sample_count < 32:
        return None

    n_fft = 2048
    while n_fft > sample_count and n_fft > 32:
        n_fft //= 2
    return n_fft


def preserve_pitch_speed(waveform, speed):
    if torchaudio_functional is None:
        raise RuntimeError("MagicAudioSpeed: preserve_pitch mode requires torchaudio.")

    sample_count = waveform.shape[-1]
    n_fft = choose_fft_size(sample_count)
    if n_fft is None:
        return resample_speed(waveform, speed)

    target_count = target_sample_count(sample_count, speed)
    if target_count == sample_count:
        return waveform.clone()

    original_dtype = waveform.dtype
    working = waveform
    if working.dtype not in (torch.float32, torch.float64):
        working = working.float()

    batch_shape = working.shape[:-1]
    flat = working.reshape(-1, sample_count)
    hop_length = max(1, n_fft // 4)
    window = torch.hann_window(n_fft, dtype=flat.dtype, device=flat.device)

    spec = torch.stft(
        flat,
        n_fft=n_fft,
        hop_length=hop_length,
        win_length=n_fft,
        window=window,
        center=True,
        pad_mode="constant",
        return_complex=True,
    )
    phase_advance = torch.linspace(
        0,
        math.pi * hop_length,
        spec.shape[-2],
        dtype=flat.dtype,
        device=flat.device,
    )[..., None]
    sped_spec = torchaudio_functional.phase_vocoder(
        spec,
        rate=float(speed),
        phase_advance=phase_advance,
    )
    sped = torch.istft(
        sped_spec,
        n_fft=n_fft,
        hop_length=hop_length,
        win_length=n_fft,
        window=window,
        center=True,
        length=target_count,
    )
    return sped.reshape(*batch_shape, target_count).to(dtype=original_dtype)


class MagicAudioSpeed:
    DESCRIPTION = (
        "Adjust AUDIO speed. Values above 1.0 make audio faster; values below 1.0 make it slower."
    )

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "audio": ("AUDIO",),
                "speed": (
                    "FLOAT",
                    {
                        "default": 1.0,
                        "min": 0.25,
                        "max": 4.0,
                        "step": 0.01,
                        "tooltip": "1.25 is 25% faster, 0.8 is 20% slower.",
                    },
                ),
                "method": (
                    AUDIO_SPEED_METHODS,
                    {
                        "default": "preserve_pitch",
                        "tooltip": "preserve_pitch keeps voice pitch stable; resample changes duration and pitch.",
                    },
                ),
            }
        }

    RETURN_TYPES = ("AUDIO",)
    RETURN_NAMES = ("audio",)
    FUNCTION = "adjust"
    CATEGORY = "MagicWrapper/Audio"

    def adjust(self, audio, speed=1.0, method="preserve_pitch"):
        waveform, sample_rate = ensure_audio(audio, node_name="MagicAudioSpeed", input_name="audio")

        speed = float(speed)
        if speed <= 0:
            raise ValueError("MagicAudioSpeed: speed must be greater than 0.")
        if method not in AUDIO_SPEED_METHODS:
            raise ValueError(
                f"MagicAudioSpeed: method must be one of {AUDIO_SPEED_METHODS}, got '{method}'."
            )

        if method == "preserve_pitch":
            adjusted_waveform = preserve_pitch_speed(waveform, speed)
        else:
            adjusted_waveform = resample_speed(waveform, speed)

        output = dict(audio)
        output["waveform"] = adjusted_waveform.contiguous()
        output["sample_rate"] = sample_rate
        return (output,)


NODE_CLASS_MAPPINGS = {
    "MagicAudioSpeed": MagicAudioSpeed,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "MagicAudioSpeed": "Magic Audio Speed",
}
