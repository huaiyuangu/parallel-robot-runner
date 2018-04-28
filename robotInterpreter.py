#!/usr/bin/python
# -*- coding: utf-8 -*-

import codecs
import os
from robot.conf import RobotSettings
from robot.running import TestSuiteBuilder
from robotfixml import fixml
import xmltodict

__author__ = 'huaiyuan.gu@gmail.com'


class RobotInterpreter(object):
    """
    parse robot test case
    parse robot xml output content
    merge xml outport files
    """
    def __init__(self, pythonLibPath):
        self.pythonpath = pythonLibPath

    def create_robot_argfile(self, argFile, test, testsuite, output):
        """
        create pybot execution argument file
        :param argFile:
        :param test:
        :param testsuite:
        :param pythonpath:
        :param output:
        :return:
        """
        file = None
        try:
            with codecs.open(argFile, 'w', "utf-8") as file:
                lines = ['--test', test, '--suite', testsuite,
                         '-W', '132', '-C', 'off', '--pythonpath', self.pythonpath,
                         '--output', output, '--log', 'None', '--report', 'None']
                print ('robot test properties: %s' % ' '.join(lines))
                for line in lines:
                    file.writelines(line)
                    file.writelines('\n')
        except Exception as e:
            print (e)
        finally:
            if file:
                file.close()

    def get_result_from_robot_output(self, output_file):
        name, status, desc, error = ('None', ' None', '', '')
        if not os.path.exists(output_file):
            error = 'Robot output file not exists'
            return (name, status, desc, error)

        with open(output_file, 'r') as fd:
            try:
                doc = xmltodict.parse(fd.read())
                test = doc['robot']['suite']['suite']['test']
                name = test['@name']
                status = test['status']['@status']
                if 'doc' in test:
                    desc = u' '.join(test['doc'].split('\n'))
                error = test['status']['#text'] if '#text' in test['status'] else ''
            except Exception as e:
                error = 'error of reading log xml file: %s' % str(e)

        return (name, status, desc, error)

    def getAllTestSuite(self, test_path):
        """
        :param test_path:
        :return:
        """
        all_items = os.listdir(test_path)
        all_suite = [i for i in all_items if os.path.isfile(os.path.join(test_path, i)) and '.robot' in i]
        all_suite = [i.decode('utf-8') for i in all_suite if i not in ('__init__.robot', 'Definitions.robot')]
        return all_suite

    def merge_xml_reports(self, test_output, xmlfiles=[]):
        """
        merge robot xml reports
        :param test_output:
        :return:
        """
        xmlfiles_fixed = []
        if xmlfiles == []:
            for name in os.listdir(test_output):
                p = os.path.join(test_output, name)
                if os.path.isdir(p):
                    continue
                if '.xml' in name:
                    xmlfiles.append(name)
        print ('xml files to fix:\n%s' % ('\n'.join(xmlfiles)))
        for name in xmlfiles:
            inpath = os.path.join(test_output, name)
            outpath = os.path.join(test_output, name.split('.')[0] + '-fixed.xml')
            fixml(inpath, outpath)
            xmlfiles_fixed.append(outpath)
            os.remove(inpath)
        print ('xml files fixing is done.')

        # merge
        logfile = '%s/log.html' % test_output
        rptfile = '%s/report.html' % test_output
        from robot.rebot import Rebot
        bot = Rebot()
        try:
            bot.main(xmlfiles_fixed, merge=True, log=logfile, report=rptfile)
            print ('robot output xml files merging is done.')
        except Exception as e:
            print ('=' * 10 + ' Robot report exception %s' % '=' * 10)
            print (e)

    def get_suite_testcases(self, test_suite_path):
        """
        parse test case name from robot test suite
        :param test_suite_path:
        :return: test names list
        """
        settings = RobotSettings()
        builder = TestSuiteBuilder(settings['SuiteNames'],
                                   settings['RunEmptySuite'])
        data = builder._parse(test_suite_path)
        tests = [test.name for test in data.testcase_table.tests]
        print ('\n'.join(tests))
        return tests

    def get_test_config(self, file_path):
        with codecs.open(file_path, 'rb', encoding='utf-8') as fh:
            lines = fh.read()
        i = 0
        ls = lines.split(u'\n')
        return ls
