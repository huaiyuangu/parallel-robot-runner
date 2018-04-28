from robotParallelRunner import RobotParalleRunner


def main():
    import sys
    import os
    import inspect

    base = os.path.dirname(os.path.abspath(inspect.getfile(inspect.currentframe())))
    robot_file_dir = os.path.join(base, 'robot_test')

    e = RobotParalleRunner(robot_file_dir, True)

    # e.kill_existed_processes()

    e.parse_robot_test_properties(robot_file_dir)

    e.start_robot_concurrent_tests()

    # e.kill_existed_processes()

    sys.exit(0)

if __name__ == '__main__':
    main()