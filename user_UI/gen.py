#!/usr/bin/python3

import signal
import sys
import argparse
import asyncio
import curses
import threading
from os import path, listdir
from threading import Thread

import aiofiles
from aiohttp import ClientSession, MultipartWriter, ClientConnectionError, ClientPayloadError, ClientResponseError, FormData


async def upload_file(url, username, password, file_path, runtime):
    async with aiofiles.open(file_path, mode='rb') as f:
        file_contents = await f.read()

    responses = runtime['responses']
    mpw = MultipartWriter()
    part = mpw.append(file_contents)
    part.set_content_disposition('attachment', filename=path.basename(file_path))

    fd = FormData()
    fd.add_field('file', file_contents, filename=path.basename(file_path))
    fd.add_field('username', username)
    fd.add_field('password', password)

    async with ClientSession() as session:
        try:
            async with session.post(url, data=fd) as response:
                response = await response.read()
                response_str = response.decode('utf-8')
                if len(response_str) > 15:
                    response_str = response_str[:12] + "..."
                responses[response_str] = responses.get(response_str, 0) + 1
        except ClientConnectionError:
            responses['CONNECTION_ERR'] = responses.get('CONNECTION_ERR', 0) + 1
        except ClientPayloadError:
            responses['PAYLOAD_ERR'] = responses.get('PAYLOAD_ERR', 0) + 1
        except ClientResponseError:
            responses['RESPONSE_ERR'] = responses.get('RESPONSE_ERR', 0) + 1


async def status_printer(runtime, stdscr):
    while runtime['running']:
        stdscr.refresh()
        stdscr.addstr(0, 0, "Uploaded: %d files, responses: %s" % (runtime['i'], runtime['responses']))
        stdscr.addstr(1, 0, "Rate: %s" % (runtime['rate'],))
        stdscr.addstr(2, 0, "q:Exit")
        stdscr.addstr(3, 0, "+:Add 0.5 to rate")
        stdscr.addstr(4, 0, "-:Subtract 0.5 from rate")
        stdscr.addstr(5, 0, "]:Double the rate ")
        stdscr.addstr(6, 0, "[:Half the rate ")
        stdscr.addstr(7, 0, "1:Set rate to 1.0")
        await asyncio.sleep(0.2)


def detect_key_press(stdscr, runtime):
    try:
        while True:
            key = stdscr.getch()
            if key == ord('q') or key == 27:
                runtime['running'] = False
                curses.echo()
                curses.nocbreak()
                curses.endwin()
                threading.main_thread().interrupt_main()
                return
            elif key == ord('=') or key == ord('+'):
                runtime['rate'] = runtime['rate'] + 0.5
            elif key == ord('-') or key == ord('_'):
                runtime['rate'] = runtime['rate'] - 0.5
            elif key == ord(']'):
                runtime['rate'] = runtime['rate'] * 2
            elif key == ord(']'):
                runtime['rate'] = runtime['rate'] / 2
            elif key == ord('1'):
                runtime['rate'] = 1
            elif key == ord('2'):
                runtime['rate'] = 2
            elif key == ord('3'):
                runtime['rate'] = 3
            elif key == ord('4'):
                runtime['rate'] = 4
            elif key == ord('5'):
                runtime['rate'] = 5
            elif key == ord('6'):
                runtime['rate'] = 6
            elif key == ord('7'):
                runtime['rate'] = 7

            runtime['rate'] = max(runtime['rate'], 0)
    except:
        return


async def load_gen(url, username, password, files_folder, runtime, stdscr):
    files_list = [path.join(files_folder, fn) for fn in listdir(files_folder)]

    asyncio.create_task(status_printer(runtime, stdscr))
    while runtime['running']:
        file_path = files_list[runtime['i'] % len(files_list)]
        upload_task = upload_file(url, username, password, file_path, runtime)
        asyncio.create_task(upload_task)
        runtime['i'] += 1
        await asyncio.sleep(1.0 / (runtime['rate'] + 0.00001))

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Generate file uploading load',
                                     formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser.add_argument('url', metavar='URL', type=str, default="http://localhost:8000/",
                        help='Base url to upload files to')
    parser.add_argument('username', metavar='username', type=str, default="username",
                        help='Username')
    parser.add_argument('password', metavar='password', type=str, default="password",
                        help='Password')
    parser.add_argument('files_folder', metavar='files_folder', nargs='?', type=str, default="./files",
                        help='files folder path')
    args=parser.parse_args()

    print("url: %s, files_folder: %s" %
          (args.url, args.files_folder))

    runtime = {
        'i': 0,
        'responses': {},
        'rate': 0.5,
        'running': True
    }

    stdscr = curses.initscr()
    curses.noecho()
    curses.cbreak()
    curses.halfdelay(1)
    thread = Thread(target=detect_key_press, args=[stdscr, runtime])
    thread.start()

    loop = asyncio.get_event_loop()
    loop.run_until_complete(load_gen(args.url, args.username, args.password, args.files_folder, runtime, stdscr))
