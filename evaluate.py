import argparse
import os

import torch
import yaml
import torch.nn as nn
from torch.utils.data import DataLoader

from utils.model import get_model, get_vocoder
from utils.tools import to_device, log, synth_one_sample
from model import CompTransTTSLoss
from dataset import Dataset


def evaluate(device, model, step, configs, logger=None, vocoder=None, len_losses=6):
    preprocess_config, model_config, train_config = configs

    # Get dataset
    learn_alignment = model_config["duration_modeling"]["learn_alignment"]
    dataset_tag = "unsup" if learn_alignment else "sup"
    dataset = Dataset(
        "val_{}.txt".format(dataset_tag), preprocess_config, model_config, train_config, sort=False, drop_last=False
    )
    batch_size = train_config["optimizer"]["batch_size"]
    loader = DataLoader(
        dataset,
        batch_size=batch_size,
        shuffle=False,
        collate_fn=dataset.collate_fn,
    )

    # Get loss function
    Loss = CompTransTTSLoss(preprocess_config, model_config, train_config).to(device).eval()

    # Evaluation
    loss_sums = [0 for _ in range(len_losses)]
    for batchs in loader:
        for batch in batchs:
            batch = to_device(batch, device)
            with torch.no_grad():
                # Forward
                output = model(*(batch[2:]), step=step)
                batch[9:11], output = output[-2:], output[:-2] # Update pitch and energy level

                # Cal Loss
                losses = Loss(batch, output, step=step)

                for i in range(len(losses)):
                    loss_sums[i] += losses[i].item() * len(batch[0])

    loss_means = [loss_sum / len(dataset) for loss_sum in loss_sums]

    message = "Validation Step {}, Total Loss: {:.4f}, Mel Loss: {:.4f}, Mel PostNet Loss: {:.4f}, Pitch Loss: {:.4f}, Energy Loss: {:.4f}, Duration Loss: {:.4f}, CTC Loss: {:.4f}, Binarization Loss: {:.4f}, GMM-MDN Loss: {:.4f}".format(
        *([step] + [l for l in loss_means])
    )

    if logger is not None:
        fig, fig_attn, wav_reconstruction, wav_prediction, tag = synth_one_sample(
            batch,
            output,
            vocoder,
            model_config,
            preprocess_config,
        )

        log(logger, step, losses=loss_means)
        if fig_attn is not None:
            log(
                logger,
                img=fig_attn,
                tag="Validation_attn/step_{}_{}".format(step, tag),
            )
        log(
            logger,
            img=fig,
            tag="Validation/step_{}_{}".format(step, tag),
        )
        sampling_rate = preprocess_config["preprocessing"]["audio"]["sampling_rate"]
        log(
            logger,
            audio=wav_reconstruction,
            sampling_rate=sampling_rate,
            tag="Validation/step_{}_{}_reconstructed".format(step, tag),
        )
        log(
            logger,
            audio=wav_prediction,
            sampling_rate=sampling_rate,
            tag="Validation/step_{}_{}_synthesized".format(step, tag),
        )

    return message
