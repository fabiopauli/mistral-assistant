# game.py
import curses
from random import randint

def main(stdscr):
    # Initialize settings
    curses.curs_set(0)
    stdscr.nodelay(1)
    stdscr.timeout(100)

    # Create game window
    sh, sw = 20, 60
    win = curses.newwin(sh, sw, 0, 0)
    win.keypad(1)
    win.border(0)
    win.nodelay(1)

    # Initial snake and food
    snake = [(4, 10), (4, 9), (4, 8)]
    food = (randint(1, sh-2), randint(1, sw-2))
    while food in snake:
        food = (randint(1, sh-2), randint(1, sw-2))
    win.addch(food[0], food[1], 'x')

    # Game logic
    score = 0
    direction = curses.KEY_RIGHT

    while True:
        win.clear()
        win.border(0)
        win.addstr(0, 2, f"Score: {score} ")

        # Draw snake and food
        for y, x in snake:
            win.addch(y, x, '@')
        win.addch(food[0], food[1], 'x')

        # Input handling
        win.refresh()
        key = win.getch()

        # Direction control
        if key in [curses.KEY_UP, curses.KEY_DOWN, curses.KEY_LEFT, curses.KEY_RIGHT]:
            direction = key

        # Move snake
        head_y, head_x = snake[0]
        if direction == curses.KEY_UP:
            new_head = (head_y-1, head_x)
        elif direction == curses.KEY_DOWN:
            new_head = (head_y+1, head_x)
        elif direction == curses.KEY_LEFT:
            new_head = (head_y, head_x-1)
        else:  # KEY_RIGHT
            new_head = (head_y, head_x+1)

        # Game over conditions
        if (new_head in snake or 
            new_head[0] in [0, sh-1] or
            new_head[1] in [0, sw-1]):
            break

        snake.insert(0, new_head)

        # Food collision
        if new_head == food:
            score += 1
            while True:
                food = (randint(1, sh-2), randint(1, sw-2))
                if food not in snake:
                    break
            win.addch(food[0], food[1], 'x')
        else:
            # Remove tail
            tail = snake.pop()
            win.addch(tail[0], tail[1], ' ')

if __name__ == "__main__":
    curses.wrapper(main)