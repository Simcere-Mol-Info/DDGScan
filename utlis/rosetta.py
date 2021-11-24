#!/usr/bin/env python

# By Jinyuan Sun, Oct, 13, 2021

import os
import pandas as pd
import numpy as np
import subprocess
import time

class Rosetta:
    def __init__(self, pdbName, relax_num, numThreads, exe='cartesian_ddg.static.linuxgccrelease', rosettadb= "/opt/rosetta_bin_linux_2021.16.61629_bundle/main/database"):
        self.exe = exe
        self.pdbname = pdbName
        self.relax_num = relax_num
        self.threads = numThreads
        # self.relaxedpdb = pdbName #for test
        self.rosettadb = rosettadb
        self.relaxedpdb: str  # for test

        #self.cutoff = cutOff
        self.result = []

    def relax(self):
        try:
            os.mkdir('rosetta_relax')
            os.system("cp  " + self.pdbname + " rosetta_relax/")
            os.chdir('rosetta_relax')
        except FileExistsError:
            os.system("cp  " + self.pdbname + " rosetta_relax/")
            os.chdir('rosetta_relax')
            pass

        with open("cart2.script","w+") as cart2:
            cart2.write("switch:cartesian\n")
            cart2.write("repeat 2\n")
            cart2.write("ramp_repack_min 0.02  0.01     1.0  50\n")
            cart2.write("ramp_repack_min 0.250 0.01     0.5  50\n")
            cart2.write("ramp_repack_min 0.550 0.01     0.0 100\n")
            cart2.write("ramp_repack_min 1     0.00001  0.0 200\n")
            cart2.write("accept_to_best\n")
            cart2.write("endrepeat")
            cart2.close()
        relax_cmd = "".join(
            ["mpirun -n " + str(self.threads) + " relax.mpi.linuxgccrelease -s " + self.pdbname + " -use_input_sc",
            " -constrain_relax_to_start_coords -ignore_unrecognized_res",
            " -nstruct " + str(self.relax_num),
            " -relax:coord_constrain_sidechains",
            " -relax:cartesian -score:weights ref2015_cart ",
            " -relax:min_type lbfgs_armijo_nonmonotone",
            " -relax:script cart2.script 1>/dev/null && sort -nk2 score.sc |head -n 1|awk '{print$22}'"]
        )
        print("==" * 20)
        print(" Relaxing your Protein: ")
        # os.system(relax_cmd)
        relaxed_pdb_name = os.popen(relax_cmd).read()
        print(" Finished relax! ")
        print("==" * 20)
        relaxed_pdb_name = os.popen("sort -nk2 score.sc |head -n 1|awk '{print$22}'").read()
        self.relaxedpdb = relaxed_pdb_name.replace("\n", "") + ".pdb"
        os.chdir("../")
        return relaxed_pdb_name.replace("\n", "") + ".pdb"

    def read_rosetta_ddgout(self, rosettaddgfilename):
        ddg_dict = {}

        ddg_array = []
        with open(rosettaddgfilename) as rosettaddg:
            for line in rosettaddg:
                #print(line.split(":")[2])
                if line.split(":")[2].strip() == "WT":
                    dg_ref = float(line.split(":")[3][1:10])
                else:
                    ddg = float(line.split(":")[3][1:10]) - dg_ref
                    ddg_array.append(ddg)
            rosettaddg.close()

        return [round(np.array(ddg_array).mean(),4), round(np.array(ddg_array).std(),4)]

    def runOneJob(self, varlist: list):
        wild, mutation, resNum, jobID = varlist
        try:
            os.mkdir(jobID)
            os.chdir(jobID)
        except FileExistsError:
            os.chdir(jobID)

        # os.popen('cp ../../rosetta_relax/' + self.relaxedpdb + ' ./')
        os.system('cp ../../rosetta_relax/' + self.relaxedpdb + ' ./')
        with open('mtfile', 'w+') as mtfile:
            mtfile.write("total 1\n")
            mtfile.write("1\n")
            mtfile.write(wild + " " + str(resNum) + " " + mutation)
            mtfile.close()

        argument_list = [self.exe, "-database", self.rosettadb,
                         "-use_input_sc",
                         "-s", self.relaxedpdb,
                         "-ddg:mut_file", "mtfile",
                         "-ddg:iterations", "3",
                         "-ddg::cartesian",
                         "-ddg::dump_pdbs", "true",
                         "-ddg:bbnbrs", "1",
                         "-score:weights", "ref2015_cart",
                         "-relax:cartesian",
                         "-relax:min_type", "lbfgs_armijo_nonmonotone",
                         "-flip_HNQ",
                         "-crystal_refine",
                         "-fa_max_dis",
                         "9.0",
                         "1>/dev/null"]
        cartddg_cmd = " ".join(argument_list)
        os.system(cartddg_cmd)
        # print(cartddg_cmd)
        os.chdir("../../")
        # return pid, '_'.join([wild, str(trueResNum), mutation])

    def pmut_scan(self, relaxed_pdb):
        pmut_scan_exe = os.popen("which pmut_scan_parallel.mpi.linuxgccrelease").read().replace("\n", "")
        rosettadb = "/".join(pmut_scan_exe.split("/")[:-3]) + "/database/"
        arg_list = [
            'mpirun',
            '-np',
            str(self.threads),
            pmut_scan_exe,
            '-database',
            rosettadb,
            '-s',
            relaxed_pdb,
            '-ex1',
            '-ex2',
            '-extrachi_cutoff 1',
            '-use_input_sc',
            '-ignore_unrecognized_res',
            '-no_his_his_pairE',
            '-multi_cool_annealer',
            '10',
            '-mute',
            'basic',
            'core'
            '>',
            "pmut.out && ls pmut.out"
        ]
        print("[INFO: ] Running pmut_scan_parallel")
        os.system(" ".join(arg_list))

    def pmut_scan_analysis(self, pmutoutfile):
        with open(pmutoutfile) as pmut_out:

            i = -1
            start_line = 0
            for line in pmut_out:
                i += 1
                line = line.replace("\x1b[0m", "")
                if line.endswith("mutation   mutation_PDB_numbering   average_ddG   average_total_energy\n"):
                    start_line = 1
                if "protocol took" in line:
                    start_line = 0
                if start_line == 1:
                    mutinfo = line.replace("\n", "").split(")")[1].split()
                    if mutinfo[2] == "average_ddG":
                        with open("All_Rosetta.score", 'w') as scorefile:
                            scorefile.write("#Score file formated by GRAPE from Rosetta.\n#mutation\tscore\tstd\n")
                            scorefile.close()
                    else:
                        with open("All_Rosetta.score", 'a+') as scorefile:
                            mut = mutinfo[0].split("-")[1]
                            scorefile.write("_".join([mut[0], mut[1:-1], mut[-1]]) + "\t" + mutinfo[2] + "\t" + "0\n")
                            scorefile.close()
        pmut_out.close()






if __name__ == '__main__':
    print("run")
    # pdbname = '1PGA.pdb'
    # chain = 'A'
    # threads = 24
    # relax_num = 200
    # prot = Rosetta(pdbname, relax_num, 'numThreads')
    # score, std = prot.read_rosetta_ddgout('rosetta_jobs/0_1_/mtfile.ddg')
    # print(score, std)
    #relax_pdb_name = prot.relax(pdbname, threads)
    #print("Using: " + relax_pdb_name)
    #os.mkdir('rosetta_jobs')
    #prot.runOneJob(relax_pdb_name, "M", chain, "Q", 1, 'rosetta_jobs/0_1/')



