#!/usr/bin/python
# -*- coding: utf-8 -*-


import codecs
import os
import time
import random
import socket
import subprocess
import threading
import signal
from robotInterpreter import RobotInterpreter
from Queue import Empty, Queue
from robot import run_cli

GLOBAL_TESTPATH = ""
ROBOT_TESTCASE_PATH = ""
ROBOT_REPORT_PATH = ""
IS_WINDOWS = False

__author__ = 'huaiyuan.gu@gmail.com'


class StreamReaderThread(object):

    def __init__(self, stream):
        self._queue = Queue()
        self._thread = None
        self._stream = stream

    def run(self):
        self._thread = threading.Thread(target=self._enqueue_output,
                                        args=(self._stream,))
        self._thread.daemon = True
        self._thread.start()

    def _enqueue_output(self, out):
        for line in iter(out.readline, b''):
            self._queue.put(line)

    def pop(self):
        result = ""
        for _ in xrange(self._queue.qsize()):
            try:
                result += self._queue.get_nowait()
            except Empty:
                pass
        return result.decode('UTF-8').rstrip(u'\n')


class Process(object):
    def __init__(self, cwd):
        self._process = None
        self._error_stream = None
        self._output_stream = None
        self._cwd = cwd
        self._port = None
        self._sock = None
        self._kill_called = False

    def run_command(self, command):
        # We need to supply stdin for subprocess, because otherways in pythonw
        # subprocess will try using sys.stdin which causes an error in windows
        subprocess_args = dict(bufsize=0,
                               stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE,
                               stdin=subprocess.PIPE,
                               cwd=self._cwd.encode('UTF-8'))
        if IS_WINDOWS:
            startupinfo = subprocess.STARTUPINFO()
            try:
                import _subprocess
                startupinfo.dwFlags |= _subprocess.STARTF_USESHOWWINDOW
            except ImportError:
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            subprocess_args['startupinfo'] = startupinfo
        else:
            subprocess_args['preexec_fn'] = os.setsid
            subprocess_args['shell'] = True
        self._process = subprocess.Popen(command.encode('UTF-8'),
                                         **subprocess_args)
        self._process.stdin.close()
        self._output_stream = StreamReaderThread(self._process.stdout)
        self._error_stream = StreamReaderThread(self._process.stderr)
        self._output_stream.run()
        self._error_stream.run()

        self._kill_called = False

    def set_port(self, port):
        self._port = port

    def get_output(self):
        return self._output_stream.pop()

    def get_errors(self):
        return self._error_stream.pop()

    def get_returncode(self):
        return self._process.returncode

    def is_alive(self):
        if not self._process: return None
        return self._process.poll() is None

    def wait(self):
        self._process.wait()

    def kill(self, force=False, killer_pid=None):
        if not self._process:
            return
        if force:
            self._process.kill()
        self.resume()  # Send so that RF is not blocked
        if IS_WINDOWS and not self._kill_called and self._port is not None:
            self._signal_kill_with_listener_server()
            self._kill_called = True
        else:
            self._kill(killer_pid or self._process.pid)

    def _signal_kill_with_listener_server(self):
        self._send_socket('kill')

    def _send_socket(self, data):
        if self._port is None:
            return  # Silent failure..
        sock = None
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.connect(('localhost', self._port))
            sock.send(data)
        finally:
            sock.close()

    def pause(self):
        self._send_socket('pause')

    def pause_on_failure(self, pause):
        if pause:
            self._send_socket('pause_on_failure')
        else:
            self._send_socket('do_not_pause_on_failure')

    def resume(self):
        self._send_socket('resume')

    def step_next(self):
        self._send_socket('step_next')

    def step_over(self):
        self._send_socket('step_over')

    def _kill(self, pid):
        if pid:
            try:
                if os.name == 'nt' and sys.version_info < (2, 7):
                    import ctypes
                    ctypes.windll.kernel32.TerminateProcess(
                        int(self._process._handle), -1)
                else:
                    os.kill(pid, signal.SIGINT)
            except OSError:
                pass


class TestRunThread(threading.Thread):
    """
    check all resource pool status and store in database
    """

    def __init__(self, name, cmd, test_name, rpt_path):
        super(TestRunThread, self).__init__(name=name)
        self.name = name
        self.test_name = test_name
        self.cmd = cmd
        self.rpt_path = rpt_path
        self.status = None
        self._stop = threading.Event()
        self.setDaemon(True)

    def stop(self):
        self._stop.set()

    def stopped(self):
        return self._stop.isSet()

    def run(self):
        for i in range(3):
            time.sleep(random.randint(1, 10))
            run_cli(self.cmd)
            name, status = self.check_test_result_from_output(self.rpt_path)
            if status == 'PASS':
                break
        self.status = status


class RobotParalleRunner(object):
    """
    Execute Robot test cases in pararrel
    """

    def __init__(self, pythonLibPath, isDebug=False):
        self.test = RobotInterpreter(pythonLibPath)
        # test path
        self.pythonpath = pythonLibPath
        self.test_target = 'product'
        self.test_type = 'smoketest'
        self.test_target_path = None
        self.test_output = None
        self.testcase_dir = None
        self.test_output_file = None
        self.proxy_output_file = None
        self.debug = isDebug
        self.test_properties_list = []
        self.proxyThread = None

    def parse_robot_test_properties(self,  robot_testcase_dir):
        """
        parse test case from .robot test suite
        generate .txt robot execution argument file
        :return:
        """
        self.test_target_path = self.testcase_dir = self.test_output = robot_testcase_dir
        self.test_output_file = os.path.join(ROBOT_REPORT_PATH, 'test_output.txt')
        self.proxy_output_file = os.path.join(ROBOT_REPORT_PATH, 'proxy_output.txt')

        print ('==== start main execution run ====')

        # test suite file
        all_suites = []
        for file in os.listdir(robot_testcase_dir):
            if file.endswith(".robot"):
                p = os.path.join(robot_testcase_dir, file)
                print ('found test suite file :%s' % p)
                all_suites.append(p)

        # clean up
        self.clean_output_files()

        # build command line for each test case
        id = -1
        for suite in all_suites:
            cases = self.test.get_suite_testcases(suite)
            for i in range(len(cases)):
                id += 1
                case = cases[i]
                argFile = os.path.join(self.test_output, 'test_%s.txt' % id)
                output = os.path.join(self.test_output, 'test_%s.xml' % id)
                suite_name = os.path.basename(suite).split('.')[0]

                # robot argument file
                # use base path in test case & suite
                base_dir = os.path.basename(self.testcase_dir)
                self.test.create_robot_argfile(argFile,
                                               u'%s.%s.%s' % (base_dir, suite_name, case),
                                               u'%s.%s' % (base_dir, suite_name),
                                               output)

                # command line to start robot execution
                cmds = ['export user_id=%s' % id,
                        'pybot --argumentfile %s %s' % ('"%s"' % argFile, '"%s"' % self.test_target_path)]

                # create properties list
                self.test_properties_list.append({'cmd': '; '.join(cmds), 'output': output,
                                                  'p': None, 'retry': 0,
                                                  'name': '', 'status': '', 'duration': 0,
                                                  'desc': '', 'error': '', 'suite': suite_name,
                                                  'ts': []})

        print ('Robot execution arguments property files & commandline list are ready.')

    def start_robot_concurrent_tests(self):
        # run concurrent tests
        self.run_test_popen(30 * 60)

        # send test report
        #self.send_report(process_ls, duration,  job_id, job_username)

        # merge report
        self.test.merge_xml_reports(self.test_output)

    def extract_robot_files(self, zf):
        """
        zip file
        :param zf:
        :return:
        """
        # extract robot files
        import os, shutil, zipfile
        if not os.path.exists(self.test_target_path):
            os.makedirs(self.test_target_path)
            print ('created direction %s' % dir)

        # clean up existed files
        for the_file in os.listdir(self.test_target_path):
            file_path = os.path.join(self.test_target_path, the_file)
            try:
                if os.path.isfile(file_path):
                    os.remove(file_path)
            except Exception as e:
                print(e)

        # extract robot files from zip file
        with zipfile.ZipFile(zf) as z:
            for rb_file in [fl for fl in z.namelist() if '.robot' in fl and 'smoketest' in fl]:
                fn = os.path.join(self.test_target_path, os.path.basename(rb_file))
                with z.open(rb_file) as zf, open(fn, 'wb') as f:
                    shutil.copyfileobj(zf, f)
                    print ('extracted file %s from %s' % (fn, zf))

    def clean_output_files(self):
        """
        clean output file: xml, txt, html
        :return:
        """

        if not os.path.exists(self.test_output):
            os.makedirs(self.test_output)

        # remove screenshots, xml, html, txt
        for item in os.listdir(self.test_output):
            p = os.path.join(self.test_output, item)
            if os.path.isdir(p):
                continue
            if '.zip' in item or '.robot' in item or '.py' in item:
                continue
            os.remove(p)
        print ('all logfines in %s are cleaned out' % self.test_output)

    def run_test_popen(self, timeout):
        """
        run python scripts in popen
        :param timeout:
        :return:
        """
        active_threads = 0
        for run in self.test_properties_list:
            p = Process(self.test_target_path)
            run['p'] = p
            run['p'].run_command(run['cmd'])
            print (run['cmd'])
            active_threads += 1

        print ('==== all %s tests started ====' % len(self.test_properties_list))
        t0 = time.time()
        finished_tests = []
        while (time.time() - t0) < timeout:
            time.sleep(5)
            if len([r['duration'] for r in self.test_properties_list if r['duration'] == 0]) == 0:
                break

            for i in range(len(self.test_properties_list)):
                run = self.test_properties_list[i]
                if run['status'] == 'PASS':
                    continue
                last_ts = run['ts'][-1] if len(run['ts']) > 0 else t0
                # kill browsers to force webdriver exists test
                if self.debug:
                    if time.time() - last_ts > 6 * 60:
                        self.kill_all_browsers()

                if run['p'].is_alive():
                    continue
                elif run['p'].is_alive() is None:
                    continue
                name, status, desc, error = self.test.get_result_from_robot_output(run['output'])
                duration = int(time.time() - last_ts)

                # status printing
                print ("Test %s, Status %s, Retry %s, Duration %s, Error %s" %
                       (name,
                        status,
                        self.test_properties_list[i]['retry'],
                        '%s (s)' % duration,
                        error))

                self.test_properties_list[i]['name'], self.test_properties_list[i]['status'] = [name, status]

                # push end timestamp
                run['ts'].append(time.time())
                if run['status'] in ('PASS', 'FAIL'):
                    if run['status'] == 'PASS' or run['retry'] >= 2 or self.debug:
                        self.test_properties_list[i]['duration'] = duration
                        self.test_properties_list[i]['desc'] = desc
                        self.test_properties_list[i]['error'] = error

                # retry failed case
                self.test_properties_list[i]['retry'] += 1
                self.test_properties_list[i]['p'].run_command(run['cmd'])

        while len(self.test_properties_list) > 0:
            finished_tests.append(self.test_properties_list.pop(0))

        return finished_tests

    def send_report(self, processes, duration, notify_room, job_id, job_username, version):
        """
        send test report email and hipchat
        :param processes: process objects list
        :return:
        """
        pass

    def send_report_slack(self, status, message, room="Test_Room", sender="*"):
        """
        :param status:
        :param message:
        :param room:
        :param sender:
        :return:
        """
        pass

    def send_report_hipchat(self, status, message, room="Test_Room", sender="*"):
        """
        :param status:
        :param message:
        :param room:
        :param sender:
        :return:
        """

        pass

    def send_report_email(self, sub, text, to, attachment_file=None):
        pass

    def kill_existed_processes(self):
        """
        for selenium test on chrome, to clean up existed browser
        :return:
        """

        cmds = ['ps -ef|grep Xvfb|grep -v grep|awk \'{print $2}\'|tr ["\\n"] [" "]|xargs kill -9',
                'ps -ef|grep chrome/chrome|grep -v grep|awk \'{print $2}\'|tr ["\\n"] [" "]|xargs kill -9']
        p = Process('/home/')
        for cmd in cmds:
            print ('to kill existed process %s' % cmd)
            p.run_command(cmd)
            time.sleep(1)
            print (p.get_output())
            # p.wait()
        print ('all existed Xvfb & chrome process are killed before starting tests.')

    def kill_all_browsers(self):
        """
        for selenium test on chrome, to clean up existed browser
        :return:
        """
        print ('debugging: kill chrome browsers to end up long test.')
        kill_chrome_cmd = '''ps -ef|grep chrome/chrome|grep -v grep|awk '{print $2}'|tr ["\n"] [" "]|xargs kill -9'''
        p = Process(self.test_target_path)
        p.run_command(kill_chrome_cmd)
        time.sleep(5)

