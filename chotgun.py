import sys
import os.path
import threading
import queue
import logging
import random
import copy
from paramiko.client import SSHClient
import re
import time
import select

class USIEngine:
    def __init__(self, name, host, engine_path,
            nodes=None, multiPV=1, threads=1,
            delay=0, delay2=0):
        self.name = name
        self.nodes=nodes
        self.multiPV = multiPV
        self.bestmove = None
        self.quit_event = threading.Event()

        self.client = SSHClient()
        self.client.load_system_host_keys()
        self.client.connect(host)
        dirname = os.path.dirname(engine_path)
        command = f'cd {dirname} && {engine_path}'
        self.stdin, self.stdout, self.stderr = \
                self.client.exec_command(command)

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
        self.send('isready')
        self.wait_for('readyok')

    def stream_watcher(self, stream):
        # for line in iter(stream.readline, b''):
        prog = re.compile('.*score cp (-?\d+) (?:multipv (\d+))? .*pv (.+)$')
        #for line in iter(stream.readline, b''):
        while (not self.quit_event.isSet()) and (not stream.closed):
            line = stream.readline().strip()
            if len(line):
                logging.debug(f'{self.name} > {line}')
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

                # TODO: bestmove
                if line.startswith('bestmove'):
                    self.bestmove = line[9:].split()[0].strip()

                self.queue.put(line)
        logging.debug(f'{self.name}: terminating the watcher thread')

    def set_option(self, name, value):
        self.send(f'setoption name {name} value {value}')

    def __del__(self):
        self.terminate()

    def terminate(self):
        self.send('quit')
        self.quit_event.set()
        self.watcher_thread.join(1)
        #self.client.close()

    def send(self, command):
        logging.debug(f'sending {command} to {self.name}')
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
                return lines

    def wait_for_bestmove(self):
        logging.debug(f'{self.name}: waiting for bestmove...')
        while self.client.get_transport().is_active():
            line = self.queue.get()
            if (line.startswith('bestmove')):
                logging.debug(f'{self.name}: found bestmove')
                bestmove = line[9:].split()[0].strip()
                self.bestmove = bestmove
                return  bestmove

    def set_position(self, pos):
        logging.debug('in set_position()')
        self.pos = pos
        self.send(f'position {pos}')

class Chotgun:
    def __init__(self, n_jobs=5):
        logging.basicConfig(level=logging.DEBUG)
        engine_path = '/home/hmatsuya/workspace/Shogi/test/yane1/exe/YaneuraOu-by-gcc'
        self.n_jobs = 5
        self.head = None
        self.status = 'wait'
        self.bestmove = None
        self.engines = []
        self.position = 'startpos'
        self.go_command = None
        for i in range(n_jobs):
            self.engines.append(USIEngine(f'yane{i}', 'localhost', engine_path, multiPV=1))

    def start(self):
        while True:
            if self.status in ['go']:
                bestmove = self.engines[self.head].bestmove
                if bestmove:
                    print(f'bestmove {bestmove}', flush=True)
                    if not 'moves' in self.position:
                        self.position += ' moves'
                    self.position += f' {bestmove}'
                    self.ponder(self.go_command)

            # check command from stdin
            #while sys.stdin in select.select([sys.stdin], [], [], 0)[0]:
            while [] != select.select([sys.stdin], [], [], 0)[0]:
                command = sys.stdin.readline().strip()
                print(f'info commandreceived: {command}', flush = True)
                logging.debug(f'command got: {command}')
                if command.startswith('position'):
                    self.position = line[len('position'):].strip()
                    logging.debug(f'position: {self.position}')

                elif command.startswith('go'):
                    logging.debug('go found')
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

                #elif command.startswith('usinewgame') or command.startswith('setoption'):
                elif False:
                    logging.debug(f'{command} command')
                    print(f'info sending command: {command}', flush=True)
                    self.send_all(command)
                    print(f'info sent command: {command}', flush=True)
                    time.sleep(0.5)

                elif command == 'quit':
                    #engine.terminate()
                    for e in self.engines:
                        e.terminate()
                    return
            else:
                logging.debug('no command yet')

            time.sleep(0.1)

    def send_all(self, command):
        for e in self.engines:
            e.send(command)

    def wait_for_all(self, command):
        for e in self.engines:
            output = e.wait_for(command)
        return output

    def go(self, command):
        logging.debug('in go_cmd()')
        self.status = 'go'
        self.go_command = command
        self.head = None
        # is there any instance pondering the position?
        for i, e in enumerate(self.engines):
            if e.status in ['go', 'ponder']:
                if e.position == self.position:
                    if e.status == 'ponder':
                        e.send('ponderhit')
                    self.head = i
                    return

        # no engine pondering the position
        logging.debug('no pondering node found')
        self.head = 1
        e = self.engines[self.head]
        e.set_position(self.position)
        e.send(command)
        e.bestmove = None
        e.status = 'go'

    def ponder(self, command):
        logging.debug('in ponder()')
        self.status = 'ponder'
        # find candidate moves
        e = self.engines[0]
        e.set_position(self.position)
        e.set_option('MultiPV', self.n_jobs)
        e.pvs = [None] * self.n_jobs
        e.send('go depth 6')
        e.wait_for_bestmove()

        # ponder the moves
        max_value = -99999
        for i in range(self.n_jobs):
            logging.debug(f'pv{i}: {e.pvs[i]}')
            if not e.pvs[i]:
                break
            self.engines[i].set_option('MultiPV', 1)
            self.engines[i].set_position(f'{self.position} {e.pvs[i][1].split()[0]}')
            if command:
                if 'ponder' not in command:
                    command = command.replace('go', 'go ponder')
            else:
                command = 'go ponder'
            self.engines[i].send(command)
            self.engines[i].status = 'ponder'


def main():
    chotgun = Chotgun(5)
    chotgun.start()
    exit(0)

if __name__ == "__main__":
    main()
    exit(0)
