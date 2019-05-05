import sys
import os.path
import threading
import queue
import logging
import random
import copy
from paramiko.client import SSHClient
import paramiko
import re
import time
import os

class USIEngine:
    def __init__(self, name, host, engine_path,
            nodes=None, multiPV=1, threads=1,
            delay=0, delay2=0):
        self.name = name
        self.nodes=nodes
        self.multiPV = multiPV
        self.quit_event = threading.Event()

        self.client = SSHClient()
        self.client.set_missing_host_key_policy(paramiko.client.WarningPolicy)
        #self.client.load_system_host_keys()
        keys = self.client.get_host_keys()
        keys.clear()
        self.client.connect(host)
        dirname = os.path.dirname(engine_path)
        command = f'cd {dirname} && {engine_path}'
        self.stdin, self.stdout, self.stderr = \
                self.client.exec_command(command, bufsize=0)

        self.queue = queue.Queue()
        self.watcher_thread = threading.Thread(target=self.stream_watcher,
                name='engine_watcher', args=(self.stdout,))
        self.watcher_thread.start()
        self.pvs = [[]] * multiPV
        self.status = 'wait'
        self.position = 'startpos'

        self.send('usi')
        self.wait_for('usiok')
        self.set_option('Threads', threads)
        self.set_option('USI_Ponder', 'false')
        self.set_option('NetworkDelay', delay)
        self.set_option('NetworkDelay2', delay2)
        self.set_option('MultiPV', multiPV)
        if nodes:
            self.set_option('NodesLimit', nodes)
        #self.send('isready')
        #self.wait_for('readyok')

    def stream_watcher(self, stream):
        # for line in iter(stream.readline, b''):
        prog = re.compile('.*score cp (-?\d+) (?:multipv (\d+))? .*pv (.+)$')
        #for line in iter(stream.readline, b''):
        while (not self.quit_event.isSet()) and (not stream.closed):
            line = stream.readline().strip()
            if len(line):
                logging.debug(f'{self.name} > {line}')
                print(f'info string {self.name} > {line}', flush=True)
                match = prog.match(line)
                if match:
                    logging.debug(f'match: {match.group(1, 2, 3)}')
                    if match.group(2):
                        # multi PV
                        num = int(match.group(2)) - 1
                    else:
                        # single PV
                        num = 0
                    logging.debug(f'{self.name}: Found score of pv {num}')
                    self.pvs[num] = [int(match.group(1)), match.group(3)]

                # bestmove
                if line.startswith('bestmove'):
                    self.status = 'wait'

                self.queue.put(line)
        logging.debug(f'{self.name}: terminating the engine watcher thread')

    def set_option(self, name, value):
        self.send(f'setoption name {name} value {value}')

    def __del__(self):
        pass
        #self.terminate()

    def terminate(self):
        self.stop()
        self.quit_event.set()
        self.send('usi')
        self.watcher_thread.join(1)
        self.send('quit')
        self.status = 'quit'
        #self.client.close()

    def send(self, command):
        logging.debug(f'sending {command} to {self.name}')
        print(f'info string sending {command} to {self.name}', flush=True)
        self.stdin.write((command + '\n').encode('utf-8'))
        self.stdin.flush()

    def wait_for(self, command):
        logging.debug(f'{self.name}: waiting for {command}')
        lines = ""
        while self.client.get_transport().is_active():
            line = self.queue.get()
            lines += f'{line}\n'
            if (line == command):
                logging.debug(f'{self.name}: found {command}')
                self.status = 'wait'
                return lines

    def wait_for_bestmove(self):
        logging.debug(f'{self.name}: waiting for bestmove...')
        infostr(f'{self.name}: waiting for bestmove...')
        while self.client.get_transport().is_active():
            line = self.queue.get()
            if (line.startswith('bestmove')):
                logging.debug(f'{self.name}: found bestmove')
                infostr(f'{self.name}: found bestmove')
                bestmove = line[9:].split()[0].strip()
                self.status = 'wait'
                return  bestmove

    def set_position(self, pos):
        self.position = pos
        self.send(f'position {pos}')

    def clear_queue(self):
        while True:
            try:
                line = self.queue.get_nowait()
                print(f'info string {self.name}: clearing queue: {line}', flush=True)
            except queue.Empty:
                break

    def ponder(self, command):
        infostr(f'{self.name}: in ponder()')
        self.go_command = command
        if 'ponder' not in command:
            command = command.replace('go', 'go ponder')
        self.send(command)
        self.status = 'ponder'
        infostr(f'{self.name}: end of ponder()')

    def stop(self):
        infostr(f'{self.name}: in stop()')
        if self.status in ['go', 'ponder']:
            self.send('stop')
            self.wait_for_bestmove()
            self.status = 'wait'


class Chotgun:
    def __init__(self, n_jobs=5):
        #logging.basicConfig(level=logging.DEBUG)
        logging.basicConfig(level=logging.INFO)
        engine_path = '/home/hmatsuya/workspace/Shogi/test/yane1/exe/YaneuraOu-by-gcc'
        engine_path = '/home/hmatsuya/cobra/exe/YaneuraOu-by-gcc'
        self.n_jobs = n_jobs
        self.head = None
        self.status = 'wait'
        self.engines = []
        self.position = 'startpos'
        self.go_command = None
        #for i in range(n_jobs):
            #self.engines.append(USIEngine(f'yane{i}', 'localhost', engine_path, multiPV=1))
        with open(os.path.join(os.path.dirname(sys.argv[0]), 'hosts.txt')) as f:
            i = 0
            for host in f:
                host = host.strip()
                if host:
                    self.engines.append(USIEngine(f'yane{i}', host, engine_path, multiPV=1))
                    i += 1
                    self.n_jobs = i

        # setup command watcher thread
        logging.debug('setting up command watcher')
        self.quit_event = threading.Event()
        self.queue = queue.Queue()
        self.watcher_thread = threading.Thread(target=self.command_watcher,
                name='command_watcher', args=(sys.stdin,))
        self.watcher_thread.start()
        logging.debug('end of __init__()')


    def start(self):
        while True:
            #if self.status in ['go']:
            if self.head is not None:
                # print the output of the head engine
                #bestmove = self.engines[self.head].bestmove
                bestmove = None
                while True:
                    head_engine = self.engines[self.head]
                    try:
                        line = head_engine.queue.get_nowait()
                        if line:
                            if line.startswith('bestmove'):
                                bestmove = line.split()[1]
                                if 'ponder' in line:
                                    ponder = line.split()[3]
                            print(line, flush=True)
                    except queue.Empty:
                        break

                if bestmove:
                    if not 'moves' in self.position:
                        self.position += ' moves'
                    self.position += f' {bestmove}'

                    if bestmove == 'resign':
                        for e in self.engines:
                            e.stop()

            # check command from stdin
            try:
                command = self.queue.get_nowait()
                print(f'info string command received: {command}', flush=True)

                if command.startswith('position'):
                    print('info string setting position')
                    self.position = command[len('position'):].strip()
                    logging.debug(f'position: {self.position}')
                    print(f'info string position set: {self.position}', flush=True)

                elif command.startswith('go'):
                    logging.debug('go found')
                    print('info string processing go command', flush=True)
                    self.go(command)

                elif command == 'usi':
                    logging.debug('usi command')
                    self.send_all('usi')
                    output = self.wait_for_all('usiok')
                    print(output, flush=True)

                elif command == 'isready':
                    logging.debug('isready command')
                    self.send_all('isready')
                    self.wait_for_all('readyok')
                    print('readyok', flush=True)

                elif command.split()[0] in ['usinewgame', 'setoption']:
                    logging.debug(f'{command} command')
                    print(f'info string sending command: {command}', flush=True)
                    self.send_all(command)
                    print(f'info string sent command: {command}', flush=True)

                elif command.split()[0] in ['gameover']:
                    logging.debug(f'{command} command')
                    print(f'info string sending command: {command}', flush=True)
                    self.send_all(command)
                    print(f'info string sent command: {command}', flush=True)
                    for e in self.engines:
                        if e.status in ['ponder', 'go']:
                            e.wait_for_bestmove()
                        e.status = 'wait'
                    self.status = 'wait'

                elif command == 'ponderhit':
                    self.ponderhit()

                elif command == 'stop':
                    if self.head is not None:
                        self.engines[self.head].send('stop')

                elif command == 'quit':
                    self.quit()

                else:
                    logging.debug(f'unrecognized command: {command}')
                    print(f'info string unrecognized command: {command}')
            #else:
            except queue.Empty:
                logging.debug('no command yet')

            time.sleep(0.001)

    def command_watcher(self, stream):
        logging.debug(f'starting command watcher thread')
        #for line in iter(stream.readline, b''):
        #while (not self.quit_event.isSet()) and (not stream.closed):
        while not self.quit_event.isSet():
            line = stream.readline().strip()
            logging.debug(f'command queueing: {line}')
            if len(line):
                self.queue.put(line)
        logging.debug(f'terminating the command watcher thread')

    def send_all(self, command):
        for e in self.engines:
            e.send(command)

    def wait_for_all(self, command):
        for e in self.engines:
            output = e.wait_for(command)
        return output

    def go(self, command):
        logging.debug('in go_cmd()')
        print('info string in go()', flush=True)
        if command.startswith('go ponder'):
            #infostr(f'ignoring go ponder: {command}')
            self.ponder_cmd(command)
            return
        self.status = 'go'
        self.go_command = command
        #self.head = None
        #infostr(f'self.head: {self.head}')
        # is there any instance pondering the position?
        for i, e in enumerate(self.engines):
            if e.status in ['go', 'ponder']:
                if e.position == self.position:
                    print(f'info string ponder hit: {e.position}', flush=True)
                    #e.clear_queue()
                    if e.status == 'ponder':
                        e.status = 'go'
                        e.send('ponderhit')
                    self.head = i
                    infostr(f'self.head: {self.head}')
                    return

        # no engine pondering the position
        logging.debug('no ponder hit')
        print('info string no ponder hit', flush=True)
        self.head = 0
        infostr(f'self.head: {self.head}')
        for i, e in enumerate(self.engines):
            #e = self.engines[self.head]
            e = self.engines[i]
            if e.status in ['go', 'ponder']:
                e.send('stop')
                e.wait_for_bestmove()
            e.set_position(self.position)
            e.bestmove = None
            if i == self.head:
                e.send(command)
                e.status = 'go'
                break
            else:
                e.send(command.replace('go', 'go ponder'))
                e.status = 'ponder'
        infostr('end of go()')

    def ponder_cmd(self, command):
        logging.debug('in ponder_cmd()')
        print('info string in ponder_cmd()', flush=True)
        self.status = 'ponder'

        # ponder the move sent by GUI
        self.head = 0
        self.engines[0].stop()
        self.engines[0].set_position(self.position)
        self.engines[0].ponder(command)
        pos, _, head_ponder = self.position.rpartition(' ')
        infostr(f'pos: {pos}, _: {_}, head_ponder: {head_ponder}')

        # find candidate moves
        e = self.engines[1]
        e.stop()
        e.set_position(pos)
        e.set_option('MultiPV', self.n_jobs)
        e.pvs = [None] * self.n_jobs
        e.send('go')
        e.wait_for_bestmove()
        e.set_option('MultiPV', 1)

        # ponder the moves
        max_value = -99999
        ie = 1
        for i in range(self.n_jobs):
            if ie >= self.n_jobs:
                break
            print(f'i: {i}, ie: {ie}', flush=True)
            print(f'head: {self.head}, head\'s status: {self.engines[self.head].status}', flush=True)
            print(f'pv{i}: {e.pvs[i]}', flush=True)

            logging.debug(f'pv{i}: {e.pvs[i]}')
            if not e.pvs[i]:
                break
            move = e.pvs[i][1].split()[0]
            if move == head_ponder:
                continue
            self.engines[ie].stop()
            position = f'{pos} {move}'
            self.engines[ie].set_position(position)
            self.engines[ie].ponder(command)
            ie += 1
        print('info string end of ponder_cmd()', flush=True)

    def ponderhit(self):
        infostr('in ponderhit()')
        self.head = 0
        e = self.engines[0]
        e.status = 'go'
        self.status = 'go'
        e.send('ponderhit')


    def quit(self):
        #engine.terminate()
        for e in self.engines:
            e.terminate()
        self.quit_event.set()
        self.watcher_thread.join(1)
        #return
        #sys.exit()
        os._exit(1)

    def __del__(self):
        pass
        #self.quit()

def infostr(s):
    print(f'info string {s}', flush=True)


def main():
    chotgun = Chotgun(n_jobs=5)
    chotgun.start()
    sys.exit()

if __name__ == "__main__":
    main()
    sys.exit()
