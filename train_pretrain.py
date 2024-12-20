"""
Description:
Author: Jiaqi Gu (jqgu@utexas.edu)
Date: 2021-10-24 16:07:22
LastEditors: ScopeX-ASU jiaqigu@asu.edu
LastEditTime: 2023-11-14 17:00:50
"""

#!/usr/bin/env python
# coding=UTF-8
import argparse
import os
import time
from typing import Iterable

import mlflow
import numpy as np
import torch
import torch.nn as nn
from pyutils.config import configs
from pyutils.general import logger as lg
from pyutils.torch_train import (
    BestKModelSaver,
    count_parameters,
    get_learning_rate,
    set_torch_deterministic,
)
from pyutils.typing import Criterion, DataLoader, Optimizer, Scheduler

from core import builder
from core.models.layers.gemm_conv2d import GemmConv2d

os.environ["CUDA_VISIBLE_DEVICES"] = "2"


def train(
    model: nn.Module,
    train_loader: DataLoader,
    optimizer: Optimizer,
    scheduler: Scheduler,
    epoch: int,
    criterion: Criterion,
    device: torch.device,
) -> None:
    model.train()
    step = epoch * len(train_loader)
    correct = 0

    for batch_idx, (data, target) in enumerate(train_loader):
        data = data.to(device, non_blocking=True)
        target = target.to(device, non_blocking=True)

        optimizer.zero_grad()

        output = model(data)

        pred = output.data.max(1)[1]
        correct += pred.eq(target.data).cpu().sum()

        classify_loss = criterion(output, target)

        loss = classify_loss

        loss.backward()

        optimizer.step()
        step += 1

        if batch_idx % int(configs.run.log_interval) == 0:
            lg.info(
                "Train Epoch: {} [{:7d}/{:7d} ({:3.0f}%)] Loss: {:.4f} Class Loss: {:.4f}".format(
                    epoch,
                    batch_idx * len(data),
                    len(train_loader.dataset),
                    100.0 * batch_idx / len(train_loader),
                    loss.data.item(),
                    classify_loss.data.item(),
                )
            )
            mlflow.log_metrics({"train_loss": loss.item()}, step=step)

    scheduler.step()
    accuracy = 100.0 * correct.float() / len(train_loader.dataset)
    lg.info(f"Train Accuracy: {correct}/{len(train_loader.dataset)} ({accuracy:.2f})%")
    mlflow.log_metrics(
        {"train_acc": accuracy.data.item(), "lr": get_learning_rate(optimizer)},
        step=epoch,
    )


def validate(
    model: nn.Module,
    validation_loader: DataLoader,
    epoch: int,
    criterion: Criterion,
    loss_vector: Iterable,
    accuracy_vector: Iterable,
    device: torch.device,
):
    model.eval()
    val_loss, correct = 0, 0
    with torch.no_grad():
        for data, target in validation_loader:
            data = data.to(device, non_blocking=True)
            target = target.to(device, non_blocking=True)
            output = model(data)

            val_loss += criterion(output, target).data.item()
            pred = output.data.max(1)[1]
            correct += pred.eq(target.data).cpu().sum()

    val_loss /= len(validation_loader)
    loss_vector.append(val_loss)

    accuracy = 100.0 * correct.float() / len(validation_loader.dataset)
    accuracy_vector.append(accuracy)

    # lg.info(
    #     "\nValidation set: Average loss: {:.4f}, Accuracy: {}/{} ({:.2f}%)\n".format(
    #         val_loss, correct, len(validation_loader.dataset), accuracy
    #     )
    # )
    mlflow.log_metrics(
        {"val_acc": accuracy.data.item(), "val_loss": val_loss}, step=epoch
    )
    return accuracy.data.item()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("config", metavar="FILE", help="config file")
    # parser.add_argument('--run-dir', metavar='DIR', help='run directory')
    # parser.add_argument('--pdb', action='store_true', help='pdb')
    args, opts = parser.parse_known_args()

    configs.load(args.config, recursive=True)
    configs.update(opts)

    if torch.cuda.is_available() and int(configs.run.use_cuda):
        torch.cuda.set_device(configs.run.gpu_id)
        device = torch.device("cuda:" + str(configs.run.gpu_id))
        torch.backends.cudnn.benchmark = True
    else:
        device = torch.device("cpu")
        torch.backends.cudnn.benchmark = False

    if configs.run.deterministic == True:
        set_torch_deterministic()

    model = builder.make_model(
        device,
        int(configs.noise.random_state) if int(configs.run.deterministic) else None,
    )
    print(model)
    # for name, parameters in model.named_parameters():
    #     print(name, ':', parameters)
    train_loader, validation_loader = builder.make_dataloader()
    optimizer = builder.make_optimizer(model)
    scheduler = builder.make_scheduler(optimizer)
    criterion = builder.make_criterion().to(device)
    saver = BestKModelSaver(k=int(configs.checkpoint.save_best_model_k))

    lg.info(f"Number of parameters: {count_parameters(model)}")

    model_name = f"{configs.model.name}_NF_N-{configs.quantize.N_bits}_Na-{configs.quantize.N_bits_a}"
    checkpoint = f"./checkpoint/{configs.checkpoint.checkpoint_dir}/{model_name}_{configs.checkpoint.model_comment}.pt"

    lg.info(f"Current checkpoint: {checkpoint}")

    mlflow.set_experiment(configs.run.experiment)
    experiment = mlflow.get_experiment_by_name(configs.run.experiment)
    mlflow.start_run(run_name=model_name)
    mlflow.log_params(
        {
            "exp_name": configs.run.experiment,
            "exp_id": experiment.experiment_id,
            "run_id": mlflow.active_run().info.run_id,
            "inbit": configs.quantize.input_bit,
            "wbit": configs.quantize.weight_bit,
            "init_lr": configs.optimizer.lr,
            "checkpoint": checkpoint,
            "restore_checkpoint": configs.checkpoint.restore_checkpoint,
            "pid": os.getpid(),
        }
    )
    lg.info(
        f"Experiment {configs.run.experiment} ({experiment.experiment_id}) starts. Run ID: ({mlflow.active_run().info.run_id}). PID: ({os.getpid()}). PPID: ({os.getppid()}). Host: ({os.uname()[1]})"
    )

    lossv, accv = [], []
    epoch = 0
    if configs.dataset.name in {"tinyimagenet"} or getattr(
        configs.checkpoint, "imagenet_pretrain", False
    ):
        import torchvision

        model2 = torchvision.models.resnet18(pretrained=True).to(device)
        conv_list1 = [i for i in model.modules() if isinstance(i, GemmConv2d)]
        conv_list2 = [i for i in model2.modules() if isinstance(i, nn.Conv2d)]
        for m1, m2 in zip(conv_list1, conv_list2):
            if m2.weight.size() == (
                m1.out_channel,
                m1.in_channel,
                m1.kernel_size,
                m1.kernel_size,
            ):
                p, q, k, _ = m1.weight.size()
                weight = (
                    m1.weight.data.permute(0, 2, 1, 3).contiguous().view(p * k, q * k)
                )
                weight[: m1.out_channel, : m1.in_channel * m1.kernel_size**2] = (
                    m2.weight.data.flatten(1)
                )
                m1.weight.data.copy_(weight.view(p, k, q, k).permute(0, 2, 1, 3))
            else:
                print(m1.weight.size(), m2.weight.size())
                p, q, k, _ = m1.weight.size()
                kernel_size1 = m1.kernel_size
                kernel_size2 = m2.kernel_size[0]
                left, right = (
                    (kernel_size2 - kernel_size1) // 2,
                    -(kernel_size2 - kernel_size1) // 2,
                )
                weight = (
                    m1.weight.data.permute(0, 2, 1, 3).contiguous().view(p * k, q * k)
                )
                weight[: m1.out_channel, : m1.in_channel * m1.kernel_size**2] = (
                    m2.weight.data[:, :, left:right, left:right].flatten(1)
                    * kernel_size2
                    / kernel_size1
                )
                m1.weight.data.copy_(weight.view(p, k, q, k).permute(0, 2, 1, 3))

        bn_list1 = [i for i in model.modules() if isinstance(i, nn.BatchNorm2d)]
        bn_list2 = [i for i in model2.modules() if isinstance(i, nn.BatchNorm2d)]
        for m1, m2 in zip(bn_list1, bn_list2):
            m1.weight.data.copy_(m2.weight)
            m1.bias.data.copy_(m2.bias)

        del model2
        torch.cuda.empty_cache()
        print("Initialize from Imagenet pre-trained ResNet-18")

    try:
        lg.info("Model pretraining...")
        lg.info(configs)

        # Add timer here
        start_time = time.perf_counter()

        for epoch in range(int(configs.run.n_epochs)):
            if configs.noise.weight_noise_std >= 1e-6:
                model.set_weight_noise(float(configs.noise.weight_noise_std))
            if configs.noise.flip_ratio >= 1e-6:
                model.set_flip_ratio(float(configs.noise.flip_ratio))

            train(model, train_loader, optimizer, scheduler, epoch, criterion, device)
            if (
                configs.noise.weight_noise_std < 1e-6
                and configs.noise.flip_ratio < 1e-6
            ):
                validate(
                    model, validation_loader, epoch, criterion, lossv, accv, device
                )
            else:
                # lg.info("Noise-Free Validation")
                model.set_weight_noise(0)
                model.set_flip_ratio(0)
                validate(model, validation_loader, epoch, criterion, [], [], device)

                model.set_weight_noise(configs.noise.weight_noise_std)
                model.set_flip_ratio(configs.noise.flip_ratio)
                tmp_lossv, tmp_accv = [], []
                for _ in range(5):
                    validate(
                        model,
                        validation_loader,
                        epoch,
                        criterion,
                        tmp_lossv,
                        tmp_accv,
                        device,
                    )
                avg_loss, std_loss = np.mean(tmp_lossv), np.std(tmp_lossv)
                avg_acc, std_acc = np.mean(tmp_accv), np.std(tmp_accv)
                lossv.append(avg_loss)
                accv.append(avg_acc)
                # lg.info("Noisy Validation: Average Loss {:.4f} ({:.4f}) Average Accuracy {:.2f}% ({:.4f})".format(avg_loss, std_loss, avg_acc, std_acc))

            end_time = time.perf_counter()
            lg.info(
                f"For Epoch = {int(configs.run.n_epochs)}, training time is {end_time - start_time:6f} seconds"
            )
            lg.info(
                f"Average Tratning time for one epoch is {(end_time - start_time)/int(configs.run.n_epochs)} seconds"
            )

            saver.save_model(
                model,
                accv[-1],
                epoch=epoch,
                path=checkpoint,
                save_model=False,
                print_msg=True,
            )

        else:
            pass

    except KeyboardInterrupt:
        lg.warning("Ctrl-C Stopped")


if __name__ == "__main__":
    main()
