##robot parallel runner


#Purpose:
    
    to run all robot test cases in parallel and merge all individual test report as united HTML report files
    all the test case information will be parsed out and included in notification report like Slack, Email etc.


#Example:

    import sys
    import os
    import inspect

    base = os.path.dirname(os.path.abspath(inspect.getfile(inspect.currentframe())))
    robot_file_dir = os.path.join(base, 'robot_test')

    e = RobotParalleRunner(robot_file_dir, True)

    e.parse_robot_test_properties(robot_file_dir)

    e.start_robot_concurrent_tests()
    
