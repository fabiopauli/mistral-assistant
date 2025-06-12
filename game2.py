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
    food = generate_food(snake, sh, sw)
    win.addch(food[0], food[1], 'x')

    # Game logic
    score = 0
    direction = curses.KEY_RIGHT
    paused = False

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

        # Pause game
        if key == ord('p'):
            paused = not paused
            if paused:
                win.addstr(sh // 2, sw // 2 - 5, "Paused")
                win.refresh()
                while True:
                    key = win.getch()
                    if key == ord('p'):
                        break
            continue

        # Direction control
        if key in [curses.KEY_UP, curses.KEY_DOWN, curses.KEY_LEFT, curses.KEY_RIGHT]:
            direction = key

        # Move snake
        if not paused:
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
                game_over_screen(win, score, sh, sw)
                break

            snake.insert(0, new_head)

            # Food collision
            if new_head == food:
                score += 1
                food = generate_food(snake, sh, sw)
                win.addch(food[0], food[1], 'x')
            else:
                # Remove tail
                tail = snake.pop()
                win.addch(tail[0], tail[1], ' ')

def generate_food(snake, sh, sw):
    while True:
        food = (randint(1, sh-2), randint(1, sw-2))
        if food not in snake:
            return food

def game_over_screen(win, score, sh, sw):
    win.clear()
    win.border(0)
    win.addstr(sh // 2, sw // 2 - 10, f"Game Over! Final Score: {score}")
    win.addstr(sh // 2 + 1, sw // 2 - 10, "Press 'r' to restart or 'q' to quit")
    win.refresh()
    while True:
        key = win.getch()
        if key == ord('r'):
            # Restart game
            win.clear()
            main(win)
            break
        elif key == ord('q'):
            # Quit game
            break

if __name__ == "__main__":
    curses.wrapper(main)