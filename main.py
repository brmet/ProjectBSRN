import curses
import random
import time
import socket
import sys
import subprocess
from multiprocessing import Process, Manager, Lock
import os
import pygame

# Initialize pygame mixer for sound effects
pygame.mixer.init()

# Load sound effects
sound1 = pygame.mixer.Sound("sound1.wav")
countdown_sound = pygame.mixer.Sound("countdown.wav")
achievement_sound = pygame.mixer.Sound("achievement.wav")
winning_sound = pygame.mixer.Sound("winning.wav")

CELL_WIDTH = 20  # Fixed width for each cell


def read_words_from_file(file_path):
    try:
        with open(file_path, 'r') as file:
            words = file.read().splitlines()
        return words
    except FileNotFoundError:
        print(f"File {file_path} not found.")
        sys.exit(1)


def create_bingo_card(words, size):
    return [random.sample(words, size) for _ in range(size)]


def display_bingo_card(window, card, start_y, start_x, size):
    for i in range(size):
        for j in range(size):
            word = card[i][j]
            if len(word) > CELL_WIDTH - 1:
                word = word[:CELL_WIDTH - 2] + '…'  # Truncate and add ellipsis
            window.addstr(start_y + i * 2, start_x + j * CELL_WIDTH, f"| {word:<{CELL_WIDTH - 1}}",
                          curses.color_pair(2))
        window.addstr(start_y + i * 2, start_x + size * CELL_WIDTH, "|")
    window.addstr(start_y + size * 2, start_x, "+" + "-" * (CELL_WIDTH * size + size - 1) + "+",curses.color_pair(5))
    window.refresh()


def check_word_on_card(card, word):
    for row in card:
        if word in row:
            return True
    return False


def mark_word_on_card(card, word):
    for row in card:
        if word in row:
            row[row.index(word)] = "X"


def check_winner(card, size):
    if all(card[i][i] == "X" for i in range(size)) or all(card[i][size - 1 - i] == "X" for i in range(size)):
        return True
    for i in range(size):
        if all(card[i][j] == "X" for j in range(size)) or all(card[j][i] == "X" for j in range(size)):
            return True
    return False


def get_input(window, prompt, y=0, x=0):
    curses.echo()
    window.addstr(y, x, prompt, curses.color_pair(4))  # Use color pair 4 for green text
    window.refresh()
    input_str = window.getstr(y, x + len(prompt)).decode('utf-8')
    curses.noecho()
    window.clear()
    return input_str


def player_process(player_id, num_players, card_size, words, player_name, server_ip, server_port):
    def main(stdscr):
        curses.start_color()
        curses.init_pair(1, curses.COLOR_CYAN, curses.COLOR_BLACK)
        curses.init_pair(4, curses.COLOR_GREEN, curses.COLOR_BLACK)  # Initialize color pair 4 for green text
        curses.init_pair(5,curses.COLOR_RED,curses.COLOR_BLACK)

        card = create_bingo_card(words, card_size)
        window = stdscr
        window.clear()
        window.addstr(0, 0, f"{player_name}'s Karte:", curses.color_pair(1))
        display_bingo_card(window, card, 2, 0, card_size)

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.connect((server_ip, server_port))
            except ConnectionRefusedError:
                print(f"Unable to connect to server at {server_ip}:{server_port}")
                sys.exit(1)

            while True:
                drawn_word = s.recv(1024).decode('utf-8')
                if not drawn_word:
                    break

                window.clear()
                window.addstr(0, 0, f"Das gezogene Wort lautet: {drawn_word}", curses.color_pair(1))
                display_bingo_card(window, card, 2, 0, card_size)

                player_input = get_input(window,
                                         f"{player_name}, haben Sie das Wort '{drawn_word}' auf Ihrer Karte? (j/n): ",
                                         card_size * 2 + 3)
                s.sendall(player_input.encode('utf-8'))

                if player_input.lower() == 'j' and check_word_on_card(card, drawn_word):
                    mark_word_on_card(card, drawn_word)
                    pygame.mixer.Sound.play(achievement_sound)
                    window.clear()
                    window.addstr(0, 0, f"{player_name} hat das Wort {drawn_word} auf der Karte!", curses.color_pair(1))
                    display_bingo_card(window, card, 2, 0, card_size)
                    window.refresh()
                    time.sleep(2)
                    s.sendall(b'SCORED')
                    if check_winner(card, card_size):
                        s.sendall(b'WIN')
                        pygame.mixer.Sound.play(winning_sound)
                        window.addstr(card_size * 2 + 5, 0, f"{player_name} hat gewonnen!", curses.color_pair(1))
                        window.refresh()
                        time.sleep(5)
                        return

    curses.wrapper(main)


def handle_player_connection(conn, addr, shared_state, num_players, lock, player_names):
    player_id = addr[1] % num_players
    while True:
        with lock:
            drawn_word = shared_state['drawn_word']
        conn.sendall(drawn_word.encode('utf-8'))
        player_response = conn.recv(1024).decode('utf-8')
        if not player_response:
            break

        with lock:
            if player_response.lower() == 'j':
                shared_state['scores'][player_id] += 1
            if player_response == 'SCORED':
                shared_state['scores'][player_id] += 1
            shared_state[f"player_{player_id}_marked"] = True

        if player_response == 'WIN':
            with lock:
                shared_state['winner'] = player_id + 1
            break


def master_process(num_players, words, shared_state, server_ip, server_port, lock, player_names):
    def main(stdscr):
        curses.start_color()
        curses.init_pair(1, curses.COLOR_GREEN, curses.COLOR_BLACK)
        curses.init_pair(2, curses.COLOR_WHITE, curses.COLOR_BLUE)
        curses.init_pair(3, curses.COLOR_RED, curses.COLOR_BLUE)

        window = stdscr
        window.clear()
        window.addstr(0, 0, "Master Terminal: Buzzword Bingo Game")

        # Create a new window for the countdown timer in the top-right corner
        max_y, max_x = stdscr.getmaxyx()
        timer_window = curses.newwin(3, 30, 0, max_x - 30)

        round_count = 0

        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind((server_ip, server_port))
                s.listen(num_players)
                connections = [s.accept()[0] for _ in range(num_players)]

                while not shared_state['winner']:
                    round_count += 1
                    drawn_word = random.choice(words)
                    with lock:
                        shared_state['drawn_word'] = drawn_word

                    window.clear()
                    window.addstr(0, 0, f"Runde {round_count}: Das gezogene Wort lautet: {drawn_word}",
                                  curses.color_pair(1))

                    # Display the scores
                    window.addstr(2, 0, "Aktueller Punktestand:")
                    for i in range(num_players):
                        window.addstr(3 + i, 0, f"{player_names[i]}: {shared_state['scores'][i]} Punkte",
                                      curses.color_pair(1))

                    window.refresh()

                    # Send the drawn word to all players
                    for conn in connections:
                        try:
                            conn.sendall(drawn_word.encode('utf-8'))
                        except ConnectionResetError:
                            window.addstr(1, 0, f"Verbindung zum Spieler verloren. Runde wird abgebrochen.",
                                          curses.color_pair(3))
                            window.refresh()
                            time.sleep(2)
                            return

                    # Countdown Timer
                    countdown_seconds = 30
                    start_time = time.time()
                    play_countdown_sound = True  # Variable, um zu verfolgen, ob der Countdown-Sound abgespielt werden soll

                    while True:
                        remaining_time = countdown_seconds - int(time.time() - start_time)
                        if remaining_time < 0:
                            break

                        # Alternating colors for blinking effect
                        for color_pair in [2, 3]:
                            timer_window.clear()
                            timer_window.addstr(0, 7, f"Zeit übrig: {remaining_time} Sekunden",
                                                curses.color_pair(color_pair))
                            timer_window.refresh()
                            time.sleep(0.5)  # Adjust to create a blinking effect

                        # Beep sound in the last 10 seconds
                        if remaining_time <= 10 and play_countdown_sound:
                            pygame.mixer.Sound.play(countdown_sound)
                            play_countdown_sound = False  # Set to False, um den Sound nur einmal abzuspielen

                        # Check if a winner has been declared during the countdown
                        with lock:
                            if shared_state['winner']:
                                break

                    # If a winner was declared, break out of the loop
                    with lock:
                        if shared_state['winner']:
                            break

                    # Wait for player responses with a timeout
                    end_time = time.time() + 2  # Allow additional time for player responses
                    while time.time() < end_time:
                        with lock:
                            if all(shared_state[f"player_{i}_marked"] for i in range(num_players)):
                                break
                        time.sleep(0.1)

                    # Reset the marked status for the next round
                    with lock:
                        for i in range(num_players):
                            shared_state[f"player_{i}_marked"] = False

                    time.sleep(2)

                window.addstr(4, 0, f"{player_names[shared_state['winner'] - 1]} hat gewonnen!", curses.color_pair(1))
                window.refresh()
                time.sleep(5)

        except KeyboardInterrupt:
            window.addstr(4, 0, "Das Spiel wurde vom Benutzer abgebrochen.", curses.color_pair(1))
            window.refresh()
            time.sleep(2)

    curses.wrapper(main)


def main():
    num_players_str = input("Bitte geben Sie die Anzahl der Spieler ein: ")
    num_players = int(num_players_str)

    card_size_str = input("Bitte geben Sie die Größe der Bingo-Karten (z.B. 5 für 5x5) ein: ")
    card_size = int(card_size_str)

    player_names = [input(f"Name des Spielers {i + 1}: ") for i in range(num_players)]

    words = read_words_from_file("words.txt")

    server_ip = '127.0.0.1'
    server_port = 65432

    manager = Manager()
    shared_state = manager.dict()
    shared_state['drawn_word'] = ''
    shared_state['winner'] = 0
    shared_state['scores'] = manager.list([0] * num_players)  # Initialize scores

    lock = Lock()

    for i in range(num_players):
        shared_state[f"player_{i}_marked"] = False

    players = []

    master_process_instance = Process(target=master_process,
                                      args=(
                                          num_players, words, shared_state, server_ip, server_port, lock, player_names))
    master_process_instance.start()

    for i in range(num_players):
        if os.name == 'nt':
            player_terminal_command = f'start cmd /k python {sys.argv[0]} {i} {num_players} {card_size} "{player_names[i]}" {server_ip} {server_port}'
        else:
            player_terminal_command = f'x-terminal-emulator -e "python3 {sys.argv[0]} {i} {num_players} {card_size} {player_names[i]} {server_ip} {server_port}"'
        player_process_instance = subprocess.Popen(player_terminal_command, shell=True)
        players.append(player_process_instance)

    master_process_instance.join()

    for player in players:
        player.terminate()


if __name__ == "__main__":
    if len(sys.argv) > 1:
        player_id = int(sys.argv[1])
        num_players = int(sys.argv[2])
        card_size = int(sys.argv[3])
        player_name = sys.argv[4]
        server_ip = sys.argv[5]
        server_port = int(sys.argv[6])
        words = read_words_from_file("words.txt")
        player_process(player_id, num_players, card_size, words, player_name, server_ip, server_port)
    else:
        main()
