import os
import sys
import time
import random
from multiprocessing import Process, Queue
import curses
from typing import List
import typer

app = typer.Typer()

# Funktion zum Initialisieren der ncurses-Benutzeroberfläche
def init_screen():
    stdscr = curses.initscr()
    curses.noecho()
    curses.cbreak()
    stdscr.keypad(True)
    return stdscr

# Funktion zum Beenden der ncurses-Benutzeroberfläche
def cleanup_screen(stdscr):
    curses.nocbreak()
    stdscr.keypad(False)
    curses.echo()
    curses.endwin()

# Funktion zum Laden von Buzzwords aus einer Textdatei
def load_buzzwords(filename):
    with open(filename, 'r') as file:
        return file.read().splitlines()

# Funktion zum Generieren einer Bingokarte
def generate_bingo_card(words, width, height):
    random.shuffle(words)
    card = [words[i:i+width] for i in range(0, width*height, width)]
    return card

# Funktion zum Überprüfen, ob eine Bingokarte gewonnen hat
def check_win(card):
    # Überprüfen auf Zeilen
    for row in card:
        if all(word == 'X' for word in row):
            return True
    # Überprüfen auf Spalten
    for col in range(len(card[0])):
        if all(card[row][col] == 'X' for row in range(len(card))):
            return True
    # Überprüfen auf Diagonalen
    if all(card[i][i] == 'X' for i in range(len(card))) or \
       all(card[i][len(card)-1-i] == 'X' for i in range(len(card))):
        return True
    return False

# Funktion zur Ausgabe der Bingokarte
def display_bingo_card(stdscr, card):
    stdscr.clear()
    height, width = stdscr.getmaxyx()
    for i, row in enumerate(card):
        for j, word in enumerate(row):
            stdscr.addstr(i, j*10, f'{word:10s}')
    stdscr.refresh()

# Funktion für den Spielerprozess
def player_process(player_id, word_file, width, height, queue):
    words = load_buzzwords(word_file)
    card = generate_bingo_card(words, width, height)
    stdscr = init_screen()
    display_bingo_card(stdscr, card)
    while True:
        key = stdscr.getch()
        if key == ord('q'):
            break
        elif key == curses.KEY_MOUSE:
            _, x, y, _, _ = curses.getmouse()
            if 0 <= x < width and 0 <= y < height:
                if card[y][x] != 'X':
                    card[y][x] = 'X'
                    display_bingo_card(stdscr, card)
                    queue.put((player_id, x, y))
    cleanup_screen(stdscr)

# Hauptanwendung
@app.command()
def main(
    word_file: str = typer.Argument(..., help="Pfad zur Textdatei mit Buzzwords"),
    width: int = typer.Option(..., help="Breite der Bingokarte"),
    height: int = typer.Option(..., help="Höhe der Bingokarte"),
    num_players: int = typer.Option(..., help="Anzahl der Spieler")
):
    queue = Queue()

    players = []
    for i in range(num_players):
        player = Process(target=player_process, args=(i+1, word_file, width, height, queue))
        player.start()
        players.append(player)

    while True:
        player_id, x, y = queue.get()
        typer.echo(f"Player {player_id} marked cell ({x}, {y})")

        # Check if any player won
        if check_win(player.get_card()):
            typer.echo(f"Player {player_id} wins!")
            break

    # Clean up processes
    for player in players:
        player.terminate()

if __name__ == "__main__":
    app()