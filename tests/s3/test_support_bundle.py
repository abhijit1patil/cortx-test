# -*- coding: utf-8 -*-
# ~!/usr/bin/python
#
# Copyright (c) 2020 Seagate Technology LLC and/or its Affiliates
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
# For any questions about this software or licensing,
# please email opensource@seagate.com or cortx-questions@seagate.com.

"""Support Bundle Test Module."""

import time
import os
import posixpath
from multiprocessing import Process, Manager

import logging
import pytest
from commons.exceptions import CTException
from commons.constants import const
from commons import commands as cmd
from commons.ct_fail_on import CTFailOn
from commons.utils.system_utils import run_remote_cmd
from commons.errorcodes import error_handler
from commons.utils.assert_utils import assert_false, assert_true
from commons.utils.config_utils import read_yaml
from commons.helpers.node_helper import Node
from libs.s3 import S3H_OBJ, CM_CFG

manager = Manager()
support_bundle_conf = read_yaml("config/s3/test_support_bundle.yaml")[1]


class TestSupportBundle:
    """Support Bundle Testsuite."""

    @classmethod
    def setup_class(cls):
        """
        Function will be invoked prior to each test case.

        It will perform all prerequisite test steps if any.
        Initializing common variable which will be used in test and
        teardown for cleanup
        """
        cls.log = logging.getLogger(__name__)
        cls.log.info("STARTED: Setup operations")
        cls.file_lst = []
        cls.pcs_start = True
        cls.host_ip = CM_CFG["nodes"][0]["host"]
        cls.uname = CM_CFG["nodes"][0]["username"]
        cls.passwd = CM_CFG["nodes"][0]["password"]
        cls.sys_bundle_dir = const.REMOTE_DEFAULT_DIR
        cls.log.info("ENDED: Setup operations")

    def setup_method(self):
        """
        Function will be invoked prior to each test case.
        """
        self.node_obj = Node(self.host_ip, self.uname, self.passwd)
        self.host_obj = None
        self.node_obj.connect(self.host_ip, username=self.uname, password=self.passwd)
        self.pysftp_obj = None
        self.node_obj.connect_pysftp(host=self.host_ip, username=self.uname, password=self.passwd)

    def remote_execution(self, hostname, username, password, cmd):
        """running remote cmd."""
        self.log.info("Remote Execution")
        return run_remote_cmd(cmd, hostname, username, password)

    def create_support_bundle(
            self,
            bundle_name,
            dest_dir,
            host_ip,
            resp_lst=None):
        """
        Function creates the support bundle collection tar file on the remote s3server.

        :param str bundle_name: Name of the bundle file to be created
        :param str dest_dir: Destination path where support bundle will be created
        :param None or List resp_lst: list containing response
        :param str host_ip: IP of the s3 remote server
        :return: (Boolean and Response)
        """
        success_msg = support_bundle_conf["support_bundle"]["success_msg"]
        final_cmd = "{} {} {}".format(cmd.BUNDLE_CMD, bundle_name, dest_dir)
        self.log.info("Command to execute : %s", final_cmd)
        resp = self.remote_execution(
            host_ip, self.uname, self.passwd, final_cmd)
        if resp[0]:
            if success_msg in str(resp[1]):
                if resp_lst:
                    resp_lst.append(True, resp[1])
                return True, resp[1]
        if resp_lst:
            resp_lst.append(False, resp[1])
        return False, resp[1]

    def get_s3_instaces_and_ism0exists(self, abs_path, check_file):
        """
        Function returns the s3server instances and m0traces files and check.

        weather m0trances are present in the remote s3server bundle support
        :param str abs_path: Absolute path of the remote server
        :param str check_file: Name of the file need to be checked
        :return: Boolean and dictionary containing the s3server instances
        and m0instances
        """
        var_mero_dict = dict()
        try:
            dir_lst = self.pysftp_obj.listdir(abs_path)
            for directory in [dir for dir in dir_lst if "s3server" in dir]:
                abs_dir_name = os.path.join(abs_path, directory)
                file_lst = self.pysftp_obj.listdir(abs_dir_name)
                var_mero_dict[abs_dir_name] = [
                    file for file in file_lst if check_file in file]
                m0_flag = [True for file in file_lst if check_file in file]
                if not any(m0_flag):
                    return False, var_mero_dict
            return True, var_mero_dict
        except CTException as error:
            self.log.error(error)
            return False, error

    def validate_time_stamp(self, org_file_path, ext_file_path):
        """
        Function compares the last modified time of the two files.

        :param str org_file_path: Absolute remote path of the server
        where actual logs are created by s3server instances
        :param str ext_file_path: Support bundle path of the file
        :return: Boolean
        """
        self.log.info(
            "Validating the time stamp of : %s with %s",
            org_file_path, ext_file_path)
        tmpstamp1 = self.pysftp_obj.stat(org_file_path)
        tmpstamp2 = self.pysftp_obj.stat(ext_file_path)
        if tmpstamp1.st_mtime == tmpstamp2.st_mtime:
            return True
        return False

    def validate_file_checksum(
            self,
            org_m0trace_lst,
            x_m0trace_lst):
        """
        Function validates and compares the md5sum checksum of list of m0traces.

        files with the actual s3server instances m0traces files
        :param list org_m0trace_lst: Actual m0traces of s3server instances files
        :param list x_m0trace_lst: Bundle support m0traces files
        :return: Boolean
        """
        md5cmd = support_bundle_conf["support_bundle"]["md5cmd"]
        for org_file in org_m0trace_lst:
            for ext_file in x_m0trace_lst:
                if org_file.split("/")[-1] == ext_file.split("/")[-1]:
                    if self.validate_time_stamp(org_file, ext_file):
                        md5cmd_1 = md5cmd.format(org_file)
                        md5cmd_2 = md5cmd.format(ext_file)
                        cheksum_res_1 = self.remote_execution(
                            self.host_ip, self.uname, self.passwd, md5cmd_1)
                        cheksum_res_2 = self.remote_execution(
                            self.host_ip, self.uname, self.passwd, md5cmd_2)
                        cheksum_res_1 = cheksum_res_1[0].split()[0].strip()
                        cheksum_res_2 = cheksum_res_2[0].split()[0].strip()
                        if cheksum_res_1 != cheksum_res_2:
                            self.log.info(
                                "Failed Checksum: %s:%s and %s:%s",
                                md5cmd_1,
                                cheksum_res_1,
                                md5cmd_2,
                                cheksum_res_2)
                            return False
        return True

    def compare_files(self, remotepath, ext_path_dict):
        """
        Function compares two remote files on the remote s3server.

        :param remotepath:
        :param dict ext_path_dict: dictionary contains bundled remote server
         path and list of m0traces files
        :return: (Boolean, m0traces_list)
        """
        x_m0trace_lst = list()
        s3_prefix = support_bundle_conf["support_bundle"]["s3server_pre"]
        m0post_fix = support_bundle_conf["support_bundle"]["m0postfix"]
        for filename in self.pysftp_obj.listdir(remotepath):
            rpath = posixpath.join(remotepath, filename)
            if s3_prefix in filename:
                org_m0trace_lst = self.pysftp_obj.listdir(rpath)
                org_m0trace_lst = [
                    os.path.join(rpath, file)
                    for file in org_m0trace_lst if m0post_fix in file]
                for dirname, x_m0trace_lst in ext_path_dict.items():
                    if dirname.split("/")[-1] == filename:
                        x_m0trace_lst = [
                            os.path.join(
                                dirname,
                                file) for file in x_m0trace_lst]
                        resp = self.validate_file_checksum(
                            org_m0trace_lst, x_m0trace_lst)
                        if not resp:
                            return False, org_m0trace_lst
        return True, x_m0trace_lst

    def pcs_start_stop_cluster(self, start_stop_cmd, status_cmd):
        """
        Function start and stops the cluster using the pcs command.

        :param string start_stop_cmd: start and stop command option
        :param string status_cmd: status command option
        :return: (Boolean and response)
        """
        cluster_msg = support_bundle_conf["support_bundle"]["cluster_msg_2"]
        self.host_obj.exec_command(start_stop_cmd)
        time.sleep(30)
        _, stdout, stderr = self.host_obj.exec_command(status_cmd)
        result = stdout.readlines() if stdout.readlines() else stderr.readlines()
        for value in result:
            if cluster_msg in value:
                return False, result
        return True, result

    def start_stop_service(self, command, host):
        """
        Function start and stop s3services using the systemctl command.

        :param str command: Actual command to be executed
        :param str host: hostname or ip of the remote s3server
        :return: respone of s3server service
        """
        self.remote_execution(
            host,
            self.uname,
            self.passwd,
            command)
        status = S3H_OBJ.get_s3server_service_status(command, host=host)
        return status

    def hctl_stop_cmd(self):
        """
        Function stops the cluster using hctl command.

        :return:(Boolean and response)
        """
        cluster_msg = support_bundle_conf["support_bundle"]["clsuter_msg_1"]
        stop_cmd = support_bundle_conf["support_bundle"]["cluster_stop_cmd"]
        status_cmd = support_bundle_conf["support_bundle"]["hctl_status"]
        resp = self.remote_execution(
            self.host_ip, self.uname, self.passwd, stop_cmd)
        self.log.info("hctl Stop resp : %s", resp)
        time.sleep(30)
        _, stdout, stderr = self.host_obj.exec_command(status_cmd)
        result = stdout.readlines() if stdout.readlines() else stderr.readlines()
        if cluster_msg in result[0].strip():
            return True, result
        return False, result

    def is_file_size(self, path):
        """
        Check if file exists and the size of the file on s3 server of extracted file.

        :param path: Absolute path of the file
        :return: bool, response
        """
        flag = False
        try:
            resp = self.pysftp_obj.stat(path)
            resp_val = resp.st_size
            flag = bool(resp.st_size > 0)
        except CTException as error:
            self.log.error(
                "%s %s: %s", const.EXCEPTION_ERROR,
                self.is_file_size.__name__, error)
            resp_val = error
        return flag, resp_val

    def teardown_method(self):
        """
        Function will be invoked after each test case.

        It will perform all cleanup operations.
        """
        self.log.info("STARTED: Teardown operations")
        if not self.pcs_start:
            self.log.info("Step : Starting cluster")
            S3H_OBJ.enable_disable_s3server_instances(resource_disable=False)
            resp = self.pcs_start_stop_cluster(
                support_bundle_conf["support_bundle"]["cluster_start_cmd"],
                support_bundle_conf["support_bundle"]["cluster_status_cmd"])
            self.pcs_start = resp[0]
        self.log.info("Step: Deleting all the remote files")
        if self.file_lst:
            for path in self.file_lst:
                self.log.info("Deleting %s", path)
                S3H_OBJ.delete_remote_dir(self.pysftp_obj, path)
        self.node_obj.disconnect()
        self.remote_execution(
            self.host_ip,
            self.uname,
            self.passwd,
            support_bundle_conf["support_bundle"]["rm_tmp_bundle_cmd"])
        self.log.info("Step : Deleted all the files")
        self.log.info("ENDED: Teardown operations")

    @pytest.mark.parallel
    @pytest.mark.s3
    @pytest.mark.tags("TEST-8024 ")
    @CTFailOn(error_handler)
    def test_dest_has_less_space_5274(self):
        """Support bundle collection when destination has less space than required."""
        self.log.info(
            "STARTED: Support bundle collection when destination has less space than required")
        test_cfg = support_bundle_conf["test_5274"]
        common_dir = test_cfg["common_dir"]
        sys_bundle_dir = test_cfg["remote_dest_dir"]
        dir_path = os.path.join(common_dir, sys_bundle_dir)
        remote_path = self.node_obj.make_dir(dir_path)
        assert_true(remote_path, f"Path not exists: {dir_path}")
        self.file_lst.append(os.path.join(dir_path))
        for i in range(test_cfg["count"]):
            bundle_name = "{}_{}".format(test_cfg["bundle_prefix"], str(i))
            self.log.info(
                "Step 1: Creating support bundle %s.tar.gz", bundle_name)
            resp = self.create_support_bundle(
                bundle_name, dir_path, self.host_ip)
            if not resp[0]:
                self.log.info(
                    "Step 1: Failed to create support bundle %s.tar.gz message : %s",
                    bundle_name, resp)
                break
            self.log.info(
                "Step 1: Successfully created support bundle message : %s, %s",
                bundle_name, resp)
            assert_false(resp[0], resp[1])
        self.log.info(
            "ENDED: Support bundle collection when destination has less space than required")

    @pytest.mark.parallel
    @pytest.mark.s3
    @pytest.mark.tags("TEST-8025")
    @CTFailOn(error_handler)
    def test_collect_triggered_simultaneously_5280(self):
        """Test multiple Support bundle collection triggered simultaneously."""
        self.log.info(
            "STARTED: Test multiple Support bundle collection triggered simultaneously")
        test_cfg = support_bundle_conf["test_5280"]
        common_dir = test_cfg["common_dir"]
        remote_path = os.path.join(common_dir, self.sys_bundle_dir)
        resp = self.node_obj.make_dir(remote_path)
        assert_true(resp, remote_path)
        self.file_lst.append(os.path.join(remote_path))
        resp_lst = manager.list()
        process_lst = []
        self.log.info(
            "Step 1: Creating support bundle parallely %s.tar.gz",
            test_cfg["bundle_prefix"])
        for i in range(test_cfg["count"]):
            bundle_name = "{}_{}".format(test_cfg["bundle_prefix"], str(i))
            process = Process(
                target=self.create_support_bundle,
                args=(bundle_name,
                      remote_path,
                      self.host_ip,
                      resp_lst))
            process_lst.append(process)
        for process in process_lst:
            process.start()
        for process in process_lst:
            process.join()
        true_flag = all([temp[0] for temp in resp_lst])
        assert_true(true_flag, resp_lst)
        self.log.info(
            "Step 1: validated all support bundle created parallely %s.tar.gz",
            test_cfg["bundle_prefix"])
        self.log.info(
            "ENDED: Test multiple Support bundle collection triggered simultaneously")

    @pytest.mark.parallel
    @pytest.mark.s3
    @pytest.mark.tags("TEST-8026")
    @CTFailOn(error_handler)
    def test_core_m0traces_all_instances_5282(self):
        """Validate Support bundle contains cores and m0traces for all instances."""
        self.log.info(
            "STARTED: Validate Support bundle contains cores and m0traces for all instances")
        test_cfg = support_bundle_conf["test_5282"]
        common_dir = test_cfg["common_dir"]
        remote_path = os.path.join(common_dir, self.sys_bundle_dir)
        resp = self.node_obj.make_dir(remote_path)
        assert_true(resp, remote_path)
        self.file_lst.append(os.path.join(remote_path))
        tar_dest_dir = os.path.join(remote_path, test_cfg["common_dir"])
        for i in range(test_cfg["count"]):
            bundle_name = "{}_{}".format(test_cfg["bundle_prefix"], str(i))
            bundle_tar_name = "s3_{}.{}".format(
                bundle_name, test_cfg["tar_postfix"])
            self.log.info(
                "Step 1: Creating support bundle %s", bundle_tar_name)
            resp = self.create_support_bundle(
                bundle_name, remote_path, self.host_ip)
            assert_true(resp[0], resp[1])
            self.log.info(
                "Step 1: Successfully created support bundle: %s, %s",
                bundle_name, resp)
            tar_file_path = os.path.join(
                remote_path, tar_dest_dir, bundle_tar_name)
            extracted_dir = os.path.join(tar_dest_dir, bundle_name)
            mkdir_cmd = test_cfg["mkdir_cmd"].format(extracted_dir)
            self.remote_execution(
                self.host_ip, self.uname, self.passwd, mkdir_cmd)
            tar_cmd = test_cfg["tar_cmd"].format(tar_file_path, extracted_dir)
            self.log.info(
                "Step 2 and 3: Extracting the tar file and "
                "validating the tar extraction: %s", tar_cmd)
            self.remote_execution(
                self.host_ip, self.uname, self.passwd, tar_cmd)
            dir_list = self.pysftp_obj.listdir(
                os.path.join(
                    extracted_dir,
                    test_cfg["tmp_dir"]))
            abs_m0trace_path = os.path.join(
                extracted_dir,
                test_cfg["tmp_dir"],
                dir_list[0],
                test_cfg["extracted_m0trace_path"])
            self.log.info(abs_m0trace_path)
            file_prefix = support_bundle_conf["support_bundle"]["m0postfix"]
            resp = self.get_s3_instaces_and_ism0exists(
                abs_m0trace_path, file_prefix)
            assert_true(resp[0], resp[1])
            var_path = self.sys_bundle_dir
            res = self.compare_files(var_path, resp[1])
            assert_true(res[0], res[1])
            self.log.info(
                "Step 2 and 3: Extracted the tar file and validated tar file")
        self.log.info(
            "ENDED: Validate Support bundle contains cores and m0traces for all instances")

    # As this test cases requires destructive operations to be performed on the node
    # causing cluster failure so disabling this test-case
    @pytest.mark.skip
    @pytest.mark.s3
    @pytest.mark.tags("TEST-8691 ")
    def test_collection_with_network_fluctuation_5272(self):
        """Support bundle collection with network fluctuation."""
        self.log.info(
            "STARTED: Test Support bundle collection with network fluctuation")
        test_cfg = support_bundle_conf["test_5272"]
        bundle_name = test_cfg["bundle_prefix"]
        common_dir = test_cfg["common_dir"]
        network_service = test_cfg["netwrk_serv_name"]
        remote_path = os.path.join(common_dir, self.sys_bundle_dir)
        resp = self.node_obj.make_dir(remote_path)
        assert_true(resp, remote_path)
        self.file_lst.append(os.path.join(remote_path))
        tar_dest_dir = os.path.join(remote_path, test_cfg["common_dir"])
        resp_lst = manager.list()
        bundle_tar_name = "s3_{}.{}".format(
            bundle_name, test_cfg["tar_postfix"])
        tar_file_path = os.path.join(
            remote_path, tar_dest_dir, bundle_tar_name)
        self.log.info(
            "Step 1: Creating support bundle %s.tar.gz", bundle_name)
        process = Process(target=self.create_support_bundle, args=(
            bundle_name, remote_path, self.host_ip, resp_lst))
        process.start()
        self.log.info(
            "Step 2: Restart network service when collection is progress")
        S3H_OBJ.restart_s3server_service(network_service)
        self.log.info("Waiting till cluster is up")
        time.sleep(test_cfg["cluster_up_delay"])
        resp = S3H_OBJ.get_s3server_service_status(network_service)
        assert_true(resp[0], resp[1])
        self.log.info(
            "Step 2: Restarted %s service successfully", network_service)
        true_flag = all([temp[0] for temp in resp_lst])
        assert_true(true_flag, resp_lst)
        resp = S3H_OBJ.is_s3_server_path_exists(tar_file_path)
        assert_false(resp[0], resp[1])
        self.log.info("Step 1: Support bundle did not created")
        self.log.info(
            "ENDED: Test Support bundle collection with network fluctuation")

    @pytest.mark.parallel
    @pytest.mark.s3
    @pytest.mark.tags("TEST-8692 ")
    @CTFailOn(error_handler)
    def test_collecion_primary_secondary_nodes_5273(self):
        """Test Support bundle collection from Primary and Secondary nodes of cluster."""
        self.log.info(
            "STARTED: Test Support bundle collection from Primary and Secondary nodes of cluster")
        test_cfg = support_bundle_conf["test_5273"]
        common_dir = test_cfg["common_dir"]
        remote_path = os.path.join(common_dir, self.sys_bundle_dir)
        resp = self.node_obj.make_dir(remote_path)
        assert_true(resp, remote_path)
        self.file_lst.append(os.path.join(remote_path))
        tar_dest_dir = os.path.join(remote_path, test_cfg["common_dir"])
        node_list = [self.host_ip, CM_CFG["nodes"][1]["host"]]
        self.log.info(
            "Step 1 Creating support bundle on primary and secondary nodes")
        for node in node_list:
            bundle_name = "{}_{}".format(test_cfg["bundle_prefix"], str(node))
            bundle_tar_name = "s3_{}.{}".format(
                bundle_name, test_cfg["tar_postfix"])
            tar_file_path = os.path.join(
                remote_path, tar_dest_dir, bundle_tar_name)
            self.log.info(
                "Step : Creating support bundle %s on node %s",
                bundle_tar_name, node)
            resp = self.create_support_bundle(
                bundle_name, remote_path, node)
            assert_true(resp[0], resp[1])
            resp = S3H_OBJ.is_s3_server_path_exists(tar_file_path, host=node)
            assert_true(resp[0], resp[1])
            self.log.info(
                "Step : Created support bundle %s on node %s",
                bundle_tar_name, node)
            self.node_obj.connect(node, username=self.uname, password=self.passwd)
            sftp = self.host_obj.open_sftp()
            S3H_OBJ.delete_remote_dir(sftp, remote_path)
            sftp.close()
        self.log.info(
            "Step 1:Support Bundle was created on primary and secondary nodes")
        self.log.info(
            "ENDED: Test Support bundle collection from Primary and Secondary nodes of cluster")

    # As this test cases requires destructive operations on the node
    # causing cluster failure so disabling this test-case
    @pytest.mark.skip
    @pytest.mark.s3
    @pytest.mark.tags("TEST-8694")
    @CTFailOn(error_handler)
    def test_collet_authservice_down_5276(self):
        """Test Support bundle collection when authserver service is down."""
        self.log.info(
            "STARTED: Test Support bundle collection when authserver service is down")
        test_cfg = support_bundle_conf["test_5276"]
        bundle_name = test_cfg["bundle_prefix"]
        common_dir = test_cfg["common_dir"]
        remote_path = os.path.join(common_dir, self.sys_bundle_dir)
        resp = self.node_obj.make_dir(remote_path)
        assert_true(resp, remote_path)
        self.file_lst.append(os.path.join(remote_path))
        tar_dest_dir = os.path.join(remote_path, test_cfg["common_dir"])
        stop_cmd = const.SYSTEM_CTL_STOP_CMD.format(test_cfg["service_name"])
        self.log.info("Step 1: Stopping the service : %s", stop_cmd)
        resp = self.start_stop_service(stop_cmd, self.host_ip)
        assert_false(resp[0], resp[1])
        self.log.info(
            "Step 1: Service %s was stopped successfully",
            test_cfg["service_name"])
        bundle_tar_name = "s3_{}.{}".format(
            bundle_name, test_cfg["tar_postfix"])
        tar_file_path = os.path.join(
            remote_path, tar_dest_dir, bundle_tar_name)
        self.log.info(
            "Step 2: Creating support bundle %s.tar.gz", bundle_name)
        resp = self.create_support_bundle(
            bundle_name, remote_path, self.host_ip)
        assert_true(resp[0], resp[1])
        resp = S3H_OBJ.is_s3_server_path_exists(tar_file_path)
        assert_true(resp[0], resp[1])
        self.log.info("Step 2: Support bundle created successfully")
        start_cmd = const.SYSTEM_CTL_START_CMD.format(test_cfg["service_name"])
        self.log.info("Step 3: Starting the service : %s", start_cmd)
        resp = self.start_stop_service(start_cmd, self.host_ip)
        assert_true(resp[0], resp[1])
        self.log.info("Step 3: Started the service : %s", start_cmd)
        self.log.info(
            "ENDED: Test Support bundle collection when authserver service is down")

    # As this test cases requires destructive operations on the node
    # causing cluster failure so disabling this test-case
    @pytest.mark.skip
    @pytest.mark.s3
    @pytest.mark.tags("TEST-8695")
    @CTFailOn(error_handler)
    def test_collection_haproxy_down_5277(self):
        """Test Support bundle collection when haproxy service is down."""
        self.log.info(
            "STARTED: Test Support bundle collection when haproxy service is down")
        test_cfg = support_bundle_conf["test_5277"]
        bundle_name = test_cfg["bundle_prefix"]
        common_dir = test_cfg["common_dir"]
        remote_path = os.path.join(common_dir, self.sys_bundle_dir)
        resp = self.node_obj.make_dir(remote_path)
        assert_true(resp, remote_path)
        self.file_lst.append(os.path.join(remote_path))
        tar_dest_dir = os.path.join(remote_path, test_cfg["common_dir"])
        stop_cmd = const.SYSTEM_CTL_STOP_CMD.format(test_cfg["service_name"])
        self.log.info("Step 1: Stopping the service : %s", stop_cmd)
        resp = self.start_stop_service(stop_cmd, self.host_ip)
        assert_false(resp[0], resp[1])
        self.log.info(
            "Step 1: Service %s was stopped successfully",
            test_cfg["service_name"])
        bundle_tar_name = "s3_{}.{}".format(
            bundle_name, test_cfg["tar_postfix"])
        tar_file_path = os.path.join(
            remote_path, tar_dest_dir, bundle_tar_name)
        self.log.info(
            "Step 2: Creating support bundle %s.tar.gz", bundle_name)
        resp = self.create_support_bundle(
            bundle_name, remote_path, self.host_ip)
        assert_true(resp[0], resp[1])
        resp = S3H_OBJ.is_s3_server_path_exists(tar_file_path)
        assert_true(resp[0], resp[1])
        self.log.info("Step 2: Support bundle created successfully")
        start_cmd = const.SYSTEM_CTL_START_CMD.format(test_cfg["service_name"])
        self.log.info("Step 3: Starting the service : %s", start_cmd)
        resp = self.start_stop_service(start_cmd, self.host_ip)
        assert_true(resp[0], resp[1])
        self.log.info("Step 3: Started the service : %s", start_cmd)
        self.log.info(
            "ENDED: Test Support bundle collection when haproxy service is down")

    # As this test cases requires destructive operations on the node
    # causing cluster failure so disabling this test-case
    @pytest.mark.skip
    @pytest.mark.s3
    @pytest.mark.tags("TEST-8696")
    @CTFailOn(error_handler)
    def test_collection_cluster_down_5278(self):
        """Test Support bundle collection when Cluster is shut down."""
        self.log.info(
            "STARTED: Test Support bundle collection when Cluster is shut down")
        test_cfg = support_bundle_conf["test_5278"]
        bundle_name = test_cfg["bundle_prefix"]
        common_dir = test_cfg["common_dir"]
        remote_path = os.path.join(common_dir, self.sys_bundle_dir)
        resp = self.node_obj.make_dir(remote_path)
        assert_true(resp, remote_path)
        self.file_lst.append(os.path.join(remote_path))
        tar_dest_dir = os.path.join(remote_path, test_cfg["common_dir"])
        self.log.info("Step 1: Stopping the cluster")
        self.pcs_start = False
        resp = self.hctl_stop_cmd()
        assert_true(resp[0], resp[1])
        self.log.info("Step 1: Cluster is stopped")
        bundle_tar_name = "s3_{}.{}".format(
            bundle_name, test_cfg["tar_postfix"])
        tar_file_path = os.path.join(
            remote_path, tar_dest_dir, bundle_tar_name)
        self.log.info(
            "Step 2: Creating support bundle %s.tar.gz", bundle_name)
        resp = self.create_support_bundle(
            bundle_name, remote_path, self.host_ip)
        assert_true(resp[0], resp[1])
        resp = S3H_OBJ.is_s3_server_path_exists(tar_file_path)
        assert_true(resp[0], resp[1])
        self.log.info(
            "ENDED: Test Support bundle collection when Cluster is shut down")

    @pytest.mark.parallel
    @pytest.mark.s3
    @pytest.mark.tags("TEST-8697")
    @CTFailOn(error_handler)
    def test_collection_one_after_other_5279(self):
        """Test multiple Support bundle collections one after the other."""
        self.log.info(
            "STARTED: Test multiple Support bundle collections one after the other")
        test_cfg = support_bundle_conf["test_5279"]
        common_dir = test_cfg["common_dir"]
        remote_path = os.path.join(common_dir, self.sys_bundle_dir)
        resp = self.node_obj.make_dir(remote_path)
        assert_true(resp, remote_path)
        self.file_lst.append(os.path.join(remote_path))
        tar_dest_dir = os.path.join(remote_path, test_cfg["common_dir"])
        self.log.info(
            "Step 1: Creating multiple support bundle")
        for i in range(test_cfg["count"]):
            bundle_name = "{}_{}".format(test_cfg["bundle_prefix"], str(i))
            bundle_tar_name = "s3_{}.{}".format(
                bundle_name, test_cfg["tar_postfix"])
            tar_file_path = os.path.join(
                remote_path, tar_dest_dir, bundle_tar_name)
            self.log.info(
                "Step : Creating support bundle %s.tar.gz", bundle_name)
            resp = self.create_support_bundle(
                bundle_name, remote_path, self.host_ip)
            assert_true(resp[0], resp[1])
            resp = S3H_OBJ.is_s3_server_path_exists(tar_file_path)
            assert_true(resp[0], resp[1])
            self.log.info(
                "Step : Created support bundle %s.tar.gz", bundle_name)
            self.log.info(
                "Step 1: Successfully created support bundle message : %s, %s",
                bundle_name, resp)
        self.log.info(
            "ENDED: Test multiple Support bundle collections one after the other")

    @pytest.mark.parallel
    @pytest.mark.s3
    @pytest.mark.tags("TEST-8698 ")
    @CTFailOn(error_handler)
    def test_s3server_logs_all_instances_5281(self):
        """Validate Support bundle contains s3server logs for all instances."""
        self.log.info(
            "STARTED: Validate Support bundle contains s3server logs for all instances")
        test_cfg = support_bundle_conf["test_5281"]
        bundle_name = test_cfg["bundle_prefix"]
        common_dir = test_cfg["common_dir"]
        remote_path = os.path.join(common_dir, self.sys_bundle_dir)
        resp = self.node_obj.make_dir(remote_path)
        assert_true(resp, remote_path)
        self.file_lst.append(os.path.join(remote_path))
        tar_dest_dir = os.path.join(remote_path, test_cfg["common_dir"])
        bundle_tar_name = "s3_{}.{}".format(
            bundle_name, test_cfg["tar_postfix"])
        tar_file_path = os.path.join(
            remote_path, tar_dest_dir, bundle_tar_name)
        self.log.info(
            "Step 1: Creating support bundle %s.tar.gz", bundle_name)
        resp = self.create_support_bundle(
            bundle_name, remote_path, self.host_ip)
        assert_true(resp[0], resp[1])
        resp = S3H_OBJ.is_s3_server_path_exists(tar_file_path)
        assert_true(resp[0], resp[1])
        self.log.info("Step 1: Support bundle tar created successfully")
        self.log.info(
            "Step 2: Validating the s3server logs in the support bundle tar")
        tar_cmd = test_cfg["tar_cmd"].format(tar_file_path, tar_dest_dir)
        self.remote_execution(
            self.host_ip, self.uname, self.passwd, tar_cmd)
        extracted_file_path = "{}{}".format(
            tar_dest_dir, test_cfg["var_path"])
        self.remote_execution(
            self.host_ip, self.uname, self.passwd, tar_cmd)
        resp = self.get_s3_instaces_and_ism0exists(
            extracted_file_path, test_cfg["s3server_pre"])
        assert_true(resp[0], resp[1])
        self.log.info(
            "Step 2: Validated the s3server logs of the support bundle tar")
        self.log.info(
            "ENDED: Validate Support bundle contains s3server logs for all instances")

    @pytest.mark.parallel
    @pytest.mark.s3
    @pytest.mark.tags("TEST-8699")
    @CTFailOn(error_handler)
    def test_authserver_logs_5283(self):
        """Validate Support bundle contains authserver logs."""
        self.log.info(
            "STARTED: Validate Support bundle contains authserver logs")
        test_cfg = support_bundle_conf["test_5283"]
        bundle_name = test_cfg["bundle_prefix"]
        common_dir = test_cfg["common_dir"]
        remote_path = os.path.join(common_dir, self.sys_bundle_dir)
        resp = self.node_obj.make_dir(remote_path)
        assert_true(resp, remote_path)
        self.file_lst.append(os.path.join(remote_path))
        tar_dest_dir = os.path.join(remote_path, test_cfg["common_dir"])
        bundle_tar_name = "s3_{}.{}".format(
            bundle_name, test_cfg["tar_postfix"])
        tar_file_path = os.path.join(
            remote_path, tar_dest_dir, bundle_tar_name)
        self.log.info(
            "Step 1: Creating support bundle %s.tar.gz", bundle_name)
        resp = self.create_support_bundle(
            bundle_name, remote_path, self.host_ip)
        assert_true(resp[0], resp[1])
        resp = S3H_OBJ.is_s3_server_path_exists(tar_file_path)
        assert_true(resp[0], resp[1])
        self.log.info("Step 1: Support bundle tar created successfully")
        self.log.info("Step 2: Validating the authserver logs in the tar")
        tar_cmd = test_cfg["tar_cmd"].format(tar_file_path, tar_dest_dir)
        self.remote_execution(
            self.host_ip, self.uname, self.passwd, tar_cmd)
        auth_server_path = "{}{}".format(
            tar_dest_dir, test_cfg["var_path"])
        resp = self.is_file_size(auth_server_path)
        assert_true(resp[0], resp[1])
        self.log.info("Step 2: Validated the authserver logs of the tar")
        self.log.info(
            "ENDED: Validate Support bundle contains authserver logs")

    @pytest.mark.parallel
    @pytest.mark.s3
    @pytest.mark.tags("TEST-8700")
    @CTFailOn(error_handler)
    def test_haproxy_logs_5284(self):
        """Validate Support bundle contains haproxy logs."""
        self.log.info(
            "STARTED: Validate Support bundle contains haproxy logs")
        test_cfg = support_bundle_conf["test_5284"]
        bundle_name = test_cfg["bundle_prefix"]
        common_dir = test_cfg["common_dir"]
        remote_path = os.path.join(common_dir, self.sys_bundle_dir)
        resp = self.node_obj.make_dir(remote_path)
        assert_true(resp, remote_path)
        self.file_lst.append(os.path.join(remote_path))
        tar_dest_dir = os.path.join(remote_path, test_cfg["common_dir"])
        bundle_tar_name = "s3_{}.{}".format(
            bundle_name, test_cfg["tar_postfix"])
        tar_file_path = os.path.join(
            remote_path, tar_dest_dir, bundle_tar_name)
        self.log.info(
            "Step 1: Creating support bundle %s.tar.gz", bundle_name)
        resp = self.create_support_bundle(
            bundle_name, remote_path, self.host_ip)
        assert_true(resp[0], resp[1])
        resp = S3H_OBJ.is_s3_server_path_exists(tar_file_path)
        assert_true(resp[0], resp[1])
        self.log.info("Step 1: Support bundle tar created successfully")
        self.log.info("Step 2: Validating the haproxy logs in the tar")
        tar_cmd = test_cfg["tar_cmd"].format(tar_file_path, tar_dest_dir)
        self.remote_execution(
            self.host_ip, self.uname, self.passwd, tar_cmd)
        auth_server_path = "{}{}".format(
            tar_dest_dir, test_cfg["var_path"])
        resp = self.is_file_size(auth_server_path)
        assert_true(resp[0], resp[1])
        self.log.info("Step 2: Validated the haproxy logs of the tar")
        self.log.info(
            "ENDED: Validate Support bundle contains haproxy logs")

    # As this test cases requires destructive operations on the node
    # causing cluster failure so disabling this test-case
    @pytest.mark.skip
    @pytest.mark.s3
    @pytest.mark.tags("TEST-8693")
    @CTFailOn(error_handler)
    def test_collection_s3server_down_5275(self):
        """Test Support bundle collection when s3server services are down."""
        self.log.info(
            "STARTED: Test Support bundle collection when s3server services are down")
        test_cfg = support_bundle_conf["test_5275"]
        bundle_name = test_cfg["bundle_prefix"]
        common_dir = test_cfg["common_dir"]
        remote_path = os.path.join(common_dir, self.sys_bundle_dir)
        resp = self.node_obj.make_dir(remote_path)
        assert_true(resp, remote_path)
        self.file_lst.append(os.path.join(remote_path))
        tar_dest_dir = os.path.join(remote_path, test_cfg["common_dir"])
        self.log.info("Step 1: Stopping the s3server services")
        self.pcs_start = False
        resp = S3H_OBJ.enable_disable_s3server_instances(
            resource_disable=test_cfg["resource_disable"])
        assert_true(resp[0], resp[1])
        resp = S3H_OBJ.check_s3services_online()
        assert_false(resp[0], resp[1])
        self.log.info("Step 1: s3server services was stopped successfully")
        bundle_tar_name = "s3_{}.{}".format(
            bundle_name, test_cfg["tar_postfix"])
        tar_file_path = os.path.join(
            remote_path, tar_dest_dir, bundle_tar_name)
        self.log.info(
            "Step 2: Creating support bundle %s.tar.gz", bundle_name)
        resp = self.create_support_bundle(
            bundle_name, remote_path, self.host_ip)
        assert_true(resp[0], resp[1])
        resp = S3H_OBJ.is_s3_server_path_exists(tar_file_path)
        assert_true(resp[0], resp[1])
        self.log.info("Step 2: Support bundle created successfully")
        resp = S3H_OBJ.enable_disable_s3server_instances(
            resource_disable=test_cfg["resource_enable"])
        assert_true(resp[0], resp[1])
        self.pcs_start = True
        self.log.info(
            "ENDED: Test Support bundle collection when s3server services are down")

    @pytest.mark.parallel
    @pytest.mark.s3
    @pytest.mark.tags("TEST-8701")
    @CTFailOn(error_handler)
    def test_collection_script_5270(self):
        """Test Support bundle collection through command/script."""
        self.log.info(
            "STARTED: Test Support bundle collection through command/script")
        test_cfg = support_bundle_conf["test_5270"]
        bundle_name = test_cfg["bundle_prefix"]
        common_dir = test_cfg["common_dir"]
        dir_path = os.path.join(common_dir, self.sys_bundle_dir)
        remote_path = self.node_obj.make_dir(dir_path)
        assert_true(remote_path, dir_path)
        self.file_lst.append(os.path.join(dir_path))
        tar_dest_dir = os.path.join(dir_path, common_dir)
        bundle_tar_name = "s3_{}.{}".format(
            bundle_name, test_cfg["tar_postfix"])
        tar_file_path = os.path.join(tar_dest_dir, bundle_tar_name)
        self.log.info(
            "Step 1: Creating support bundle %s.tar.gz", bundle_name)
        resp = self.create_support_bundle(
            bundle_name, dir_path, self.host_ip)
        assert_true(resp[0], resp[1])
        self.log.info(
            "Step 1: Created support bundle %s.tar.gz", bundle_name)
        self.log.info("Step 2: Verifying that support bundle is created")
        resp = S3H_OBJ.is_s3_server_path_exists(tar_file_path)
        assert_true(resp[0], resp[1])
        self.log.info("Step 2: Verified that support bundle is created")
        self.log.info(
            "ENDED: Test Support bundle collection through command/script")

    @pytest.mark.parallel
    @pytest.mark.s3
    @pytest.mark.tags("TEST-8689")
    @CTFailOn(error_handler)
    def test_system_configs_5285(self):
        """Validate Support bundle contains system related configs."""
        self.log.info(
            "STARTED: Validate Support bundle contains system related configs")
        cfg_5285 = support_bundle_conf["test_5285"]
        bundle_name = cfg_5285["bundle_prefix"]
        common_dir = cfg_5285["common_dir"]
        ex_cfg_files = []
        dir_path = os.path.join(common_dir, self.sys_bundle_dir)
        remote_path = self.node_obj.make_dir(dir_path)
        assert_true(remote_path, f"Failed to create directory: {dir_path}")
        self.file_lst.append(os.path.join(dir_path))
        tar_dest_dir = os.path.join(dir_path, cfg_5285["common_dir"])
        bundle_name = "{0}_{1}".format(bundle_name, str(cfg_5285["count"]))
        bundle_tar_name = "s3_{0}.{1}".format(
            bundle_name, cfg_5285["tar_postfix"])
        self.log.info(
            "Step 1: Creating support bundle %s", bundle_tar_name)
        resp = self.create_support_bundle(
            bundle_name, dir_path, self.host_ip)
        assert_true(resp[0], resp[1])
        self.log.info(
            "Step 1: Created support bundle successfully: %s %s",
            bundle_name, resp)
        tar_file_path = os.path.join(
            dir_path, tar_dest_dir, bundle_tar_name)
        self.log.info(
            "Step 2: Extracting the support bundle %s", bundle_tar_name)
        tar_cmd = cfg_5285["tar_cmd"].format(tar_file_path, tar_dest_dir)
        self.remote_execution(
            self.host_ip, self.uname, self.passwd, tar_cmd)
        self.log.info(
            "Step 2: Extracted the support bundle %s", bundle_tar_name)
        self.log.info(
            "Step 3: Checking config files are present under %s after "
            "extracting a support bundle", tar_dest_dir)
        cfg_5285 = const.CFG_FILES
        for file in cfg_5285:
            file_path = f"{tar_dest_dir}{file}"
            resp = S3H_OBJ.is_s3_server_path_exists(file_path)
            assert_true(resp[0], resp[1])
            ex_cfg_files.append(file_path)
        self.log.info(
            "Step 3: Checked for config files are present under %s after "
            "extracting a support bundle", tar_dest_dir)
        self.log.info(
            "Step 4: Verifying contents of extracted config files with system config files")
        resp = self.validate_file_checksum(cfg_5285, ex_cfg_files)
        assert_true(resp, f"validate file checksum failed.")
        self.log.info(
            "Step 4: Verified that contents of extracted config files are "
            "same as system config files")
        self.log.info(
            "ENDED: Validate Support bundle contains system related configs")

    @pytest.mark.parallel
    @pytest.mark.s3
    @pytest.mark.tags("TEST-8690")
    @CTFailOn(error_handler)
    def test_collect_system_info_stats_5286(self):
        """Validate Support bundle collects system information and stats."""
        self.log.info(
            "STARTED: Validate Support bundle collects system information and stats")
        cfg_5286 = support_bundle_conf["test_5286"]
        bundle_name = cfg_5286["bundle_prefix"]
        common_dir = cfg_5286["common_dir"]
        stat_files = []
        remote_path = os.path.join(common_dir, self.sys_bundle_dir)
        resp = self.node_obj.make_dir(remote_path)
        assert_true(resp, remote_path)
        self.file_lst.append(os.path.join(remote_path))
        tar_dest_dir = os.path.join(remote_path, cfg_5286["common_dir"])
        bundle_name = "{0}_{1}".format(bundle_name, str(cfg_5286["count"]))
        bundle_tar_name = "s3_{0}.{1}".format(
            bundle_name, cfg_5286["tar_postfix"])
        self.log.info(
            "Step 1: Creating support bundle %s", bundle_tar_name)
        resp = self.create_support_bundle(
            bundle_name, remote_path, self.host_ip)
        assert_true(resp[0], resp[1])
        self.log.info(
            "Step 1: Created support bundle successfully: %s, %s",
            bundle_name, resp)
        tar_file_path = os.path.join(
            remote_path, tar_dest_dir, bundle_tar_name)
        self.log.info(
            "Step 2: Extracting the support bundle %s", bundle_tar_name)
        tar_cmd = cfg_5286["tar_cmd"].format(tar_file_path, tar_dest_dir)
        self.remote_execution(
            self.host_ip, self.uname, self.passwd, tar_cmd)
        self.log.info(
            "Step 2: Extracted the support bundle %s", bundle_tar_name)
        self.log.info(
            "Step 3: Checking if system level stat files are collected")
        stat_files_dir = self.pysftp_obj.listdir(os.path.join(
            tar_dest_dir, cfg_5286["stat_files_dir"]))
        bundle_stat_dir = [
            dir for dir in stat_files_dir if cfg_5286["stat_dir_name"] in dir][0]
        stat_dir_path = os.path.join(
            tar_dest_dir,
            cfg_5286["stat_files_dir"],
            bundle_stat_dir)
        for file in cfg_5286["stat_files"]:
            stat_file_path = f"{stat_dir_path}/{file}"
            resp = S3H_OBJ.is_s3_server_path_exists(stat_file_path)
            assert_true(resp[0], resp[1])
            stat_files.append(stat_file_path)
        self.log.info(
            "Step 3: Checked that system level stat files are collected")
        self.log.info(
            "Step 4 : Verifying that system level stat files are not empty")
        for file in stat_files:
            resp = self.is_file_size(file)
            assert_true(resp[0], resp[1])
        self.log.info(
            "Step 4 : Verified that system level stat files are not empty")
        self.log.info(
            "ENDED: Validate Support bundle collects system information and stats")