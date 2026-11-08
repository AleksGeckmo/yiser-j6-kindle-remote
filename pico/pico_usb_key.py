# MicroPython for RP2350 (Pico 2 / clone). First-draft USB_KEY sender for a Jieli AC6323A.
#
# WIRING (all grounds common!):
#   Pico GND  -> board ground pad (yellow)
#   Pico GP2  -> 1 kohm -> D+ test pad (pad left of the purple pad; chip pin 12)
#   Pico GP3  -> 1 kohm -> D- test pad (purple pad; chip pin 11)
#   Optional: 4.7 kohm from each of GP2/GP3 (Pico side) up to Pico 3V3 (see doc: idle line should read high)
#   Chip power: EITHER the battery, OR Pico 3V3 -> VBAT pad (pink) with the battery lead disconnected. Never both.
#   Do NOT connect the Pico 3V3 to anything else, and leave the board's VBUS (red) pad unconnected for now.
#
# USAGE (in Thonny or mpremote):
#   listen()   - drives nothing; prints every change on D+/D- for 15 s (power-cycle the chip while it runs)
#   run()      - repeatedly sends the key; prints ACK if both lines get pulled low by the chip.
#                Start run(), THEN power the chip (connect VBAT jumper) so the key is present at boot.
#
# Protocol as documented at kagaimiq.github.io/jielie/isp/usb/usb-key.html (for AC696N, unverified on AC6323A):
#   16-bit key 0x16EF, MSB first, data on D-, clock on D+, chip latches on D+ rising edge, ~50 kHz,
#   repeat until the chip pulls both D+ and D- low for 1-2 ms.

from machine import Pin
import time

DP_PIN, DM_PIN = 2, 3
KEY = 0x16EF
HALF_US = 10            # half clock period in microseconds (MicroPython overhead makes it slower in practice)
ACK_LOW_US = 800        # both lines low at least this long counts as an ack
ATTEMPT_GAP_MS = 2      # idle time between key repeats where we listen for the ack


def _release(pull=Pin.PULL_UP):
    dp = Pin(DP_PIN, Pin.IN, pull)
    dm = Pin(DM_PIN, Pin.IN, pull)
    return dp, dm


def listen(seconds=15):
    dp, dm = _release()
    last = (dp.value(), dm.value())
    print("listening, start state D+=%d D-=%d" % last)
    t0 = time.ticks_ms()
    next_beat = 5000
    while time.ticks_diff(time.ticks_ms(), t0) < seconds * 1000:
        cur = (dp.value(), dm.value())
        el = time.ticks_diff(time.ticks_ms(), t0)
        if cur != last:
            print("%6d ms  D+=%d D-=%d" % (el, cur[0], cur[1]))
            last = cur
        if el >= next_beat:
            print("%6d ms  (heartbeat) D+=%d D-=%d" % (el, cur[0], cur[1]))
            next_beat += 5000
    print("done")


def _send_key():
    dp = Pin(DP_PIN, Pin.OUT, value=1)
    dm = Pin(DM_PIN, Pin.OUT, value=1)
    for i in range(15, -1, -1):
        dm.value((KEY >> i) & 1)   # data first
        dp.value(0)                # clock low
        time.sleep_us(HALF_US)
        dp.value(1)                # rising edge: chip latches the bit
        time.sleep_us(HALF_US)
    dm.value(1)                    # return to idle-high


def _wait_ack(window_ms):
    # Lines float (no pull) while listening, so we don't feed the chip through a pull-up.
    dp, dm = _release(pull=None)
    t_end = time.ticks_add(time.ticks_ms(), window_ms)
    low_since = None
    while time.ticks_diff(t_end, time.ticks_ms()) > 0:
        both_low = (dp.value() == 0 and dm.value() == 0)
        now = time.ticks_us()
        if both_low:
            if low_since is None:
                low_since = now
            elif time.ticks_diff(now, low_since) >= ACK_LOW_US:
                # Candidate ack. A floating line can just drift low, so confirm: a real ack is the chip
                # actively holding both lines low, which still reads low against a pull-up.
                dp, dm = _release(pull=Pin.PULL_UP)
                time.sleep_us(150)
                ok = (dp.value() == 0 and dm.value() == 0)
                _release(pull=None)
                if ok:
                    return True
                low_since = None
        else:
            low_since = None
    return False


def _send_key_on(clk, dat):
    """Send the key once with an explicit clock pin and data pin (Pin objects already set as outputs)."""
    for i in range(15, -1, -1):
        dat.value((KEY >> i) & 1)
        clk.value(0)
        time.sleep_us(HALF_US)
        clk.value(1)
        time.sleep_us(HALF_US)


VBAT_SENSE_PIN = 5      # GP5 <- midpoint of a 1.5k/1.5k divider from the board's B+ pad


def auto(cycles=10, window_ms=300):
    """Wait for the chip to be powered (VBAT sense goes high), then send the key for window_ms,
    alternating which USB line is the clock, then release both lines so the PC can enumerate
    the chip. Repeats for each power-up, up to `cycles` times. Lines are never driven while
    the chip is unpowered."""
    led = _led()
    sense = Pin(VBAT_SENSE_PIN, Pin.IN, Pin.PULL_DOWN)
    _release(pull=None)
    for c in range(1, cycles + 1):
        print("cycle %d: waiting for power OFF then ON (pull the jumper, then push it in)" % c)
        while sense.value():          # wait until unpowered
            time.sleep_ms(5)
        if led:
            led.value(0)
        while not sense.value():      # wait for power-up
            pass
        t_on = time.ticks_us()
        dp = Pin(DP_PIN, Pin.OUT, value=1)
        dm = Pin(DM_PIN, Pin.OUT, value=1)
        if led:
            led.value(1)
        n = 0
        t_end = time.ticks_add(time.ticks_ms(), window_ms)
        while time.ticks_diff(t_end, time.ticks_ms()) > 0:
            _send_key_on(dp, dm)      # D+ = clock, D- = data
            dp.value(1); dm.value(1)
            _send_key_on(dm, dp)      # D- = clock, D+ = data
            dp.value(1); dm.value(1)
            n += 1
        _release(pull=None)
        print("cycle %d: power seen, first key %d us after power-up, %d key pairs sent, lines released"
              % (c, time.ticks_diff(time.ticks_us(), t_on) - window_ms * 1000, n))
    if led:
        led.value(0)
    print("done")


def timed(countdown_s=6, window_ms=2500):
    """LED blinks fast during the countdown (power must be OFF), then goes solid:
    push the power jumper in right then. The key is sent for window_ms (both line
    orders, alternating), then both lines are released for the PC."""
    led = _led()
    _release(pull=None)
    print("countdown %d s: keep the jumper OUT" % countdown_s)
    t0 = time.ticks_ms()
    while time.ticks_diff(time.ticks_ms(), t0) < countdown_s * 1000:
        if led:
            led.value((time.ticks_diff(time.ticks_ms(), t0) // 150) & 1)
        time.sleep_ms(10)
    if led:
        led.value(1)
    print("LED solid: push the jumper in NOW")
    dp = Pin(DP_PIN, Pin.OUT, value=1)
    dm = Pin(DM_PIN, Pin.OUT, value=1)
    n = 0
    t_end = time.ticks_add(time.ticks_ms(), window_ms)
    while time.ticks_diff(t_end, time.ticks_ms()) > 0:
        _send_key_on(dp, dm)      # D+ = clock, D- = data
        dp.value(1); dm.value(1)
        _send_key_on(dm, dp)      # D- = clock, D+ = data
        dp.value(1); dm.value(1)
        n += 1
    _release(pull=None)
    if led:
        led.value(0)
    print("sent %d key pairs; lines released, LED off" % n)


POWER_PIN = 6           # GP6 -> board-side row of the (removed) battery jumper, i.e. the chip's VBAT


def _power_pin():
    try:
        return Pin(POWER_PIN, Pin.OUT, value=0, drive=Pin.DRIVE_3)   # strongest drive (~12 mA)
    except Exception:
        return Pin(POWER_PIN, Pin.OUT, value=0)


def power_test(seconds=12):
    """Power the chip from GP6 with the data lines released, so it boots its normal firmware.
    If it reconnects over Bluetooth, the Pico pin can power it."""
    _release(pull=None)
    pwr = _power_pin()
    pwr.value(0)
    time.sleep_ms(1500)
    t0 = time.ticks_ms()
    pwr.value(1)
    print("power ON from GP6 for %d s" % seconds)
    time.sleep(seconds)
    pwr.value(0)
    print("power OFF (%d ms)" % time.ticks_diff(time.ticks_ms(), t0))


def attempts(delays_ms=(0, 2, 10, 30, 80, 200), half_us_list=(10, 25), window_ms=150,
             off_ms=1500, listen_ms=4500):
    """Fully automatic entry attempts. For every (half-period, delay) pair: power off, power on,
    wait delay_ms, send the key (both line orders, alternating) for window_ms, release the lines,
    then leave the chip powered for listen_ms so the PC can see it enumerate."""
    global HALF_US
    led = _led()
    pwr = _power_pin()
    t_start = time.ticks_ms()
    n = 0
    for half in half_us_list:
        HALF_US = half
        for d in delays_ms:
            n += 1
            _release(pull=None)
            pwr.value(0)
            if led:
                led.value(0)
            time.sleep_ms(off_ms)
            t_on = time.ticks_diff(time.ticks_ms(), t_start)
            pwr.value(1)
            if d:
                time.sleep_ms(d)
            dp = Pin(DP_PIN, Pin.OUT, value=1)
            dm = Pin(DM_PIN, Pin.OUT, value=1)
            if led:
                led.value(1)
            t_end = time.ticks_add(time.ticks_ms(), window_ms)
            pairs = 0
            while time.ticks_diff(t_end, time.ticks_ms()) > 0:
                _send_key_on(dp, dm)
                dp.value(1); dm.value(1)
                _send_key_on(dm, dp)
                dp.value(1); dm.value(1)
                pairs += 1
            _release(pull=None)
            if led:
                led.value(0)
            print("attempt %2d at %6.1f s: half=%d us, delay=%d ms, %d key pairs; listening %d ms"
                  % (n, t_on / 1000, half, d, pairs, listen_ms))
            time.sleep_ms(listen_ms)
    pwr.value(0)
    _release(pull=None)
    print("all attempts done, power OFF")


def enter(window_ms=150):
    """The recipe that worked on 2026-11-08: power-cycle the chip from GP6, send the key immediately
    (both line orders, 10 us half-period) for window_ms, release the lines, and LEAVE IT POWERED
    so the PC can talk to the BD19 UBOOT1.00 device."""
    global HALF_US
    HALF_US = 10
    pwr = _power_pin()
    _release(pull=None)
    pwr.value(0)
    time.sleep_ms(1500)
    pwr.value(1)
    dp = Pin(DP_PIN, Pin.OUT, value=1)
    dm = Pin(DM_PIN, Pin.OUT, value=1)
    t_end = time.ticks_add(time.ticks_ms(), window_ms)
    while time.ticks_diff(t_end, time.ticks_ms()) > 0:
        _send_key_on(dp, dm)
        dp.value(1); dm.value(1)
        _send_key_on(dm, dp)
        dp.value(1); dm.value(1)
    _release(pull=None)
    print("key sent; chip left POWERED with lines released")


def power_off():
    _release(pull=None)
    _power_pin().value(0)
    print("chip power OFF")


def uart_capture(seconds=25, pin=DP_PIN, baud=115200):
    """Receive the remote's debug UART (8N1) on `pin` with a PIO state machine and print it as text."""
    import rp2

    # NOTE: wait() uses the ABSOLUTE gpio number (2); the pin-relative form misbehaved on this board.
    @rp2.asm_pio(in_shiftdir=rp2.PIO.SHIFT_RIGHT, fifo_join=rp2.PIO.JOIN_RX)
    def uart_rx():
        label("start")
        wait(0, gpio, 2)              # start bit
        set(x, 7)              [10]   # to the middle of bit 0
        label("bitloop")
        in_(pins, 1)
        jmp(x_dec, "bitloop")  [6]
        jmp(pin, "good_stop")         # valid stop bit?
        wait(1, gpio, 2)              # framing error: wait for idle, drop the byte
        jmp("start")
        label("good_stop")
        push(block)

    rx = Pin(pin, Pin.IN, Pin.PULL_UP)
    sm = rp2.StateMachine(0, uart_rx, freq=8 * baud, in_base=rx, jmp_pin=rx)
    sm.active(1)
    print("capturing UART on GP%d at %d baud for %d s" % (pin, baud, seconds))
    t0 = time.ticks_ms()
    t_end = time.ticks_add(t0, seconds * 1000)
    buf = bytearray(24000)
    n = 0
    first_ms = None
    pin_obj = Pin(pin)
    high_samples = low_samples = 0
    while time.ticks_diff(t_end, time.ticks_ms()) > 0:
        while sm.rx_fifo():
            b = (sm.get() >> 24) & 0xFF
            if n < len(buf):
                buf[n] = b
            if first_ms is None:
                first_ms = time.ticks_diff(time.ticks_ms(), t0)
            n += 1
        if pin_obj.value():
            high_samples += 1
        else:
            low_samples += 1
    sm.active(0)
    print("[capture done: %d bytes, first byte at %s ms; line idle-high %d%% of samples]"
          % (n, first_ms, 100 * high_samples // max(1, high_samples + low_samples)))
    data = bytes(buf[:min(n, len(buf))])
    print("[zero bytes: " + str(data.count(b'\x00')) + " of " + str(len(data)) + "]")
    txt = bytearray()
    for b in data[:6000]:
        if b == 10 or (b >= 32 and b < 127):
            txt.append(b)
        elif b != 13:
            txt.append(46)
    for ln in bytes(txt).decode().split('\n')[:80]:
        print(ln[:160])
    import binascii
    print("[hex head] " + binascii.hexlify(data[:96]).decode())
    return data


def debug_boot(log_seconds=12):
    """Power-cycle the remote from GP6, count heartbeat toggles on D- (GP3) during the first 1.5 s,
    then capture the debug UART on D+ (GP2). USB cable must be unplugged from the PC."""
    _release(pull=None)
    pwr = _power_pin()
    pwr.value(0)
    time.sleep_ms(1500)
    dm = Pin(DM_PIN, Pin.IN, Pin.PULL_DOWN)
    dp = Pin(DP_PIN, Pin.IN, Pin.PULL_UP)
    pwr.value(1)
    t0 = time.ticks_ms()
    last_m, edges_m, edges_p, last_p = dm.value(), 0, 0, dp.value()
    while time.ticks_diff(time.ticks_ms(), t0) < 1500:
        m = dm.value(); p_ = dp.value()
        if m != last_m:
            edges_m += 1; last_m = m
        if p_ != last_p:
            edges_p += 1; last_p = p_
    print("heartbeat: D- edges %d, D+ edges %d in first 1.5 s (D- now %d)" % (edges_m, edges_p, dm.value()))
    data = uart_capture(log_seconds)
    pwr.value(0)
    _release(pull=None)
    print("power off")
    return data


def _led():
    try:
        return Pin("LED", Pin.OUT)
    except Exception:
        return None


def run(max_seconds=105, lead_s=25):
    """Phase 1 (lead_s): lines released, LED blinks slowly  -> cut the chip's power now.
       Phase 2: key is sent repeatedly, LED solid           -> restore the chip's power now.
    """
    led = _led()
    print("phase 1: lines released for %d s - cut the chip's power" % lead_s)
    _release(pull=None)
    t0 = time.ticks_ms()
    while time.ticks_diff(time.ticks_ms(), t0) < lead_s * 1000:
        if led:
            led.value((time.ticks_diff(time.ticks_ms(), t0) // 500) & 1)
        time.sleep_ms(20)
    if led:
        led.value(1)
    print("phase 2: sending key - restore the chip's power now")
    t0 = time.ticks_ms()
    n = 0
    while time.ticks_diff(time.ticks_ms(), t0) < (max_seconds - lead_s) * 1000:
        _send_key()
        n += 1
        if _wait_ack(ATTEMPT_GAP_MS):
            _release(pull=None)      # let go of both lines completely
            print("ACK after %d key sends - lines released. Plug the USB cable into the PC NOW." % n)
            return True
    print("no ack after %d sends" % n)
    _release(pull=None)
    if led:
        led.value(0)
    return False
