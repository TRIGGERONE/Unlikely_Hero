import os
import subprocess
from multiprocessing import Pool

import mlflow
from pyutils.general import ensure_dir, logger
from pyutils.config import configs

root = "Experiment/log/cifar10/vgg8/salience_comparison"
script = "scan_defender_IS.py"
config_file = "config/cifar10/vgg8/defender/defender.yml"
configs.load(config_file, recursive=True)


def task_launcher(args):
    pres = ["python3", script, config_file]
    (N_bit, salience) = args

    with open(os.path.join(root, f"Protection_Index_Gen_IS_Salience_{salience}_{N_bit}.log"), "w") as wfid:
        exp = [
            f"--quantize.N_bits={N_bit}",
            f"--defense.salience={salience}"
        ]
        logger.info(f"running command {pres + exp}")
        logger.info(f"N_bits is  {N_bit}")
        subprocess.call(pres + exp, stderr=wfid, stdout=wfid)


if __name__ == "__main__":
    ensure_dir(root)
    mlflow.set_experiment(configs.run.experiment)  # set experiments first

    tasks = [
        (
            8,
            "first-order"
        )
    ]

    with Pool(1) as p:
        p.map(task_launcher, tasks)
    logger.info(f"Exp: {configs.run.experiment} Done.")