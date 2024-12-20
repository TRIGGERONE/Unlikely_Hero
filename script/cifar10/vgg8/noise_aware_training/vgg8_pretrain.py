import os
import subprocess
from multiprocessing import Pool

import mlflow
from pyutils.general import ensure_dir, logger
from pyutils.config import configs

root = 'Experiment/log/cifar10/vgg8/pretrain_NA'
script = 'train_pretrain.py'
config_file = 'config/cifar10/vgg8/pretrain_NA.yml'
configs.load(config_file, recursive=True)

def task_launcher(args):
    pres = [
        'python3',
        script,
        config_file
    ]
    n_epochs, N_bits = args
    with open(os.path.join(root, f'pretrain_NA_vgg8-{n_epochs}_Nbit_{N_bits}.log'), 'w') as wfid:
        exp = [
            f"--run.n_epochs={n_epochs}"
        ]
        logger.info(f"running command {pres + exp}")
        subprocess.call(pres + exp, stderr=wfid, stdout=wfid)


if __name__ == '__main__':
    ensure_dir(root)
    mlflow.set_experiment(configs.run.experiment)  # set experiments first

    tasks = [(
        20,
        8
    )]  # assign training epochs
    with Pool(1) as p:
        p.map(task_launcher, tasks)
    logger.info(f"Exp: {configs.run.experiment} Done.")