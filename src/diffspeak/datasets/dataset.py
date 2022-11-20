# Inspired by
# https://github.com/lmnt-com/diffwave/blob/master/src/diffwave/dataset.py
# ==============================================================================

import random
from glob import glob
from pathlib import Path

import numpy as np
import torch
import torch.nn.functional as F
import torchaudio
from hydra.utils import get_original_cwd
from omegaconf import DictConfig


class AudioDataset(torch.utils.data.Dataset):
    def __init__(self, cfg: DictConfig):
        super().__init__()
        self.cfg = cfg
        self.filenames = []

        self.dataset_root = Path(get_original_cwd()).joinpath(self.cfg.datamodule.path)
        self.spectrograms_path = self.dataset_root / "spectrograms"
        self.filenames = glob(f"{self.dataset_root}/**/*.wav", recursive=True)

    def __len__(self):
        return len(self.filenames)


class ConditionalDataset(AudioDataset):
    def __init__(self, cfg: DictConfig):
        super().__init__(cfg)

    def __getitem__(self, idx):
        audio_filename = self.filenames[idx]
        spec_filename = f"{self.spectrograms_path / Path(audio_filename).name}.spec.npy"
        signal, _ = torchaudio.load(audio_filename)
        spectrogram = np.load(
            spec_filename
        )  # TODO: this needs to be torch? Maybe we can save it as torch during the preprocessing
        return {"audio": signal[0], "spectrogram": spectrogram.T}


class UnconditionalDataset(AudioDataset):
    def __init__(self, cfg):
        super().__init__(cfg)

    def __getitem__(self, idx):
        audio_filename = self.filenames[idx]
        signal, _ = torchaudio.load(audio_filename)
        return {"audio": signal[0], "spectrogram": None}


class Collator:
    def __init__(self, cfg):
        self.cfg = cfg

    def collate(self, minibatch):
        samples_per_frame = self.cfg.datamodule.preprocessing.hop_samples

        for record in minibatch:
            if self.cfg.datamodule.params.unconditional:
                # Filter out records that aren't long enough.
                if len(record["audio"]) < self.cfg.datamodule.params.audio_len:
                    del record["spectrogram"]
                    del record["audio"]
                    continue

                start = random.randint(
                    0, record["audio"].shape[-1] - self.cfg.datamodule.params.audio_len
                )
                end = start + self.cfg.datamodule.params.audio_len
                record["audio"] = torch.squeeze(record["audio"][start:end])
                record["audio"] = F.pad(
                    record["audio"],
                    (0, (end - start) - len(record["audio"])),
                    mode="constant",
                    value=0,
                )
            else:
                # Filter out records that aren't long enough.
                if (
                    len(record["spectrogram"])
                    < self.cfg.datamodule.params.crop_mel_frames
                ):
                    del record["spectrogram"]
                    del record["audio"]
                    continue

                start = random.randint(
                    0,
                    record["spectrogram"].shape[0]
                    - self.cfg.datamodule.params.crop_mel_frames,
                )
                end = start + self.cfg.datamodule.params.crop_mel_frames
                record["spectrogram"] = record["spectrogram"][start:end].T

                start *= samples_per_frame
                end *= samples_per_frame
                record["audio"] = torch.squeeze(
                    record["audio"][start:end]
                )  # Depends on the shape here
                record["audio"] = F.pad(
                    record["audio"],
                    (0, (end - start) - len(record["audio"])),
                    mode="constant",
                    value=0,
                )

        audio = torch.stack(
            [record["audio"] for record in minibatch if "audio" in record]
        )

        if self.cfg.datamodule.params.unconditional:
            return {
                "audio": audio,
                "spectrogram": None,
            }
        spectrogram = torch.stack(
            [record["spectrogram"] for record in minibatch if "spectrogram" in record]
        )
        return {
            "audio": audio,
            "spectrogram": spectrogram,
        }


def lj_speech_from_path(cfg):
    if cfg.datamodule.params.unconditional:
        dataset = UnconditionalDataset(cfg)
    else:  # with spectrograms
        dataset = ConditionalDataset(cfg)
    return dataset
