from enum import Enum
from gpiozero import LED, Button
import signal
import sun
from datetime import datetime,time,timedelta
from time import sleep

# Coordinates
LAT = 50.905505
LONG = 4.6754048
SUN = sun.Sun(lat=LAT,long=LONG)

# Default times (in seconds)
DEFAULT_SLEEP = 10
OPENING_THRESHOLD = timedelta(seconds=2)
CLOSING_THRESHOLD = timedelta(seconds=2) 

class State(Enum):
  opening = 1
  opening_stopped = 2
  open = 3
  closing = 4
  closing_stopped = 5
  closed = 6
  unknown = 7
  error = 8


def blink(led, state):
  if state == State.opening or state == State.closing:
    led.blink(0.5,0.1)
  if state == State.open or state == State.closed:
    led.blink(0.1,10)
  if state == State.unknown:
    led.blink(1,1)
  if state == State.error:
    led.blink(0.1,0.2)


def desired_state():
  """
  Calculate the desired state of a door:
  - when the sun's out: State.open
  - otherwise: State.closed
  """
  rise = SUN.sunrise()
  if rise.hour < 6:
    rise = time(6,0,0,0,sun.TZ_LOCAL) # ten vroegste om 06u00
  set = SUN.sunset()
  now = datetime.now(sun.TZ_LOCAL).time()
  if now > rise and now < set:
    return State.open
  else:
    return State.closed


def transition_state(actual, desired):
  """
  Calculate the state that permits a door to make the transition from an 'actual' to a 'desired' state.
  """
  if actual == State.error or actual == desired:
    return actual
  if desired == State.open:
    return State.opening
  if desired == State.closed:
    return State.closing
  raise ValueError('States: {a}, {d}'.format(a=repr(actual),d=repr(desired)))


def toggle_state(current):
  """
  Calculate the "next" state for a given 'current' state (= when the button is pressed)
  """
  if current == State.unknown or current == State.error:
    return State.open
  if current == State.opening:
    return State.opening_stopped
  if current == State.opening_stopped or current == State.open:
    return State.closed
  if current == State.closing:
    return State.closing_stopped
  if current == State.closing_stopped or current == State.closed:
    return State.open
  raise ValueError('State: {c}'.format(c=repr(current)))


def is_moving(state):
  return state == State.opening or state == State.closing



class Motor:
  running = False
  direction = False # False ~ going up; True ~ going down

  def __init__(self,
               onoff_pin=14,   # output pin: controll on/off state of motor
               dir_pin=15):    # output pin: controll direction of motor
    self.onoff = LED(onoff_pin)
    self.dir = LED(dir_pin)

  def set_state(self, state):
    self.running = state == State.opening or state == State.closing
    self.direction = state == State.opening
    self.__update()

  def __update(self):
    self.dir.value = self.direction and self.running
    self.onoff.value = self.running



class Door:
  state = None
  desired_state = None
  closing_started = None
  opening_started = None

  def __init__(self,
               led_pin=3,      # output pin: indicator LED
               btn_pin=4,      # input pin: operating button
               onoff_pin=14,   # output pin: controll on/off state of motor
               dir_pin=15,     # output pin: controll direction of motor
               upper_pin=2,    # input pin: upper bounds
               lower_pin=18):  # input pin: lower bounds
    # output
    self.led = LED(led_pin)
    self.motor = Motor(onoff_pin, dir_pin)

    # input
    self.btn = Button(btn_pin)
    self.upper = Button(upper_pin)
    self.lower = Button(lower_pin)

    self.btn.when_pressed = self.__toggle
    self.upper.when_pressed = self.__set_open
    self.lower.when_pressed = self.__set_closed

    if self.upper.is_pressed:
      s = State.open
    elif self.lower.is_pressed:
      s = State.closed
    else:
      s = State.unknown
    self.__set_state(s)

#    signal.pause()

  def run(self):
    while True:
      self.__set_desired(desired_state())
      sleep(DEFAULT_SLEEP)

  def __set_desired(self, desired):
    while self.state != desired: # FIXME busy waiting, blokkeert upper.- / lower.when_pressed
      self.__set_state(transition_state(self.state, desired))
      if self.state == State.error:
        return

  def __set_state(self, state):
    if self.state == state:
      if is_moving(state):
        return self.__check_blocked()
      return DEFAULT_SLEEP

    # update self.opening_started and self.closing_started
    if state == State.opening:
      self.opening_started = datetime.now(sun.TZ_LOCAL)
    else:
      self.opening_started = None
    if state == State.closing:
      self.closing_started = datetime.now(sun.TZ_LOCAL)
    else:
      self.closing_started = None

    # apply state change
    self.state = state
    blink(self.led, state)
    self.motor.set_state(state)

    return 0

  def __check_blocked(self):
    now = datetime.now(sun.TZ_LOCAL)
    if self.state == State.opening and self.lower.is_pressed and now > self.opening_started + OPENING_THRESHOLD:
      return self.__set_state(State.error)
    if self.state == State.closing and self.upper.is_pressed and now > self.closing_started + CLOSING_THRESHOLD:
      return self.__set_state(State.error)
    return 0

  def __toggle(self):
    self.__set_desired(toggle_state(self.state))

  def __set_open(self):
    """
    Mark this door as "open".
    If the door is closing, we check if the door is blocked: 
    - When the delay of CLOSING_THRESHOLD has elapsed, the state is set to State.error.
    - If the delay has not yet passed, no action is taken.
    Otherwise, the state is set to State.open.
    """
    if self.state == State.closing:
      if datetime.now(sun.TZ_LOCAL) > self.closing_started + CLOSING_THESHOLD:
        self.__set_state(State.error)
      return

    self.__set_state(State.open)

  def __set_closed(self):
    """
    Mark this door as "closed".
    If the door is opening, we check if the door is blocked:
    - When the delay of OPENING_THRESHOLD has elapsed, the state is set to State.error.
    - If the delay has not yet passed, no action is taken.
    Otherwise, the state is set to State.closed
    """
    if self.state == State.opening: 
      if datetime.now(sun.TZ_LOCAL) > self.opening_started + OPENING_THRESHOLD:
        self.__set_state(State.error)
      return

    self.__set_state(State.closed)



if __name__ == '__main__':
  try:
    door = Door()
    door.run()
    #motor = Motor()
    #motor.run()
  except KeyboardInterrupt:
    motor.halt()
