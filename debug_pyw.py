
import os, sys, time, traceback

with open('debug_output.log', 'w') as log:
    log.write('1. script entered\n')
    try:
        import desktop_app
        log.write('2. desktop_app imported\n')
        desktop_app.main()
        log.write('3. desktop_app.main() exited normally\n')
    except Exception as e:
        log.write(f'EX: {e}\n')
        traceback.print_exc(file=log)
