#!/usr/bin/env python3

# 2ping for MicroPython
# Copyright (C) 2017 Ryan Finnie
#
# This program is free software; you can redistribute it and/or
# modify it under the terms of the GNU General Public License
# as published by the Free Software Foundation; either version 2
# of the License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA
# 02110-1301, USA.

try:
    import ustruct as struct
except:
    import struct
try:
    import usocket as socket
except:
    import socket
try:
    import utime as time
except:
    import time
try:
    import uos as os
except:
    import os
import gc


def twoping_checksum(d):
    # 2ping checksum requires just slightly higher than a 16-bit work space.
    # Working from the spec, the internal checksum state will often be
    # (0xffff + small number), so 17 bits.  With that in mind, we can save
    # computation time by accepting we need a 32-bit number and working
    # within that.  This function is compatibile with the spec reference
    # pseudocode but much faster.  The downside is if the input is larger
    # than 64KiB, the internal checksum state can surpass 32 bits.
    checksum = 0

    for i in range(len(d)):
        if i & 1:
            checksum += d[i]
        else:
            checksum += d[i] << 8

    checksum = ((checksum >> 16) + (checksum & 0xffff))
    checksum = ((checksum >> 16) + (checksum & 0xffff))
    checksum = ~checksum & 0xffff

    if checksum == 0:
        checksum = 0xffff

    return checksum


class MT19937:
    def _int32(self, x):
        # Get the 32 least significant bits.
        return int(0xFFFFFFFF & x)

    def __init__(self, seed):
        # Initialize the index to 0
        self.index = 624
        self.mt = [0] * 624
        self.mt[0] = seed  # Initialize the initial state to the seed
        for i in range(1, 624):
            self.mt[i] = self._int32(
                1812433253 * (self.mt[i - 1] ^ self.mt[i - 1] >> 30) + i)

    def extract_number(self):
        if self.index >= 624:
            self.twist()

        y = self.mt[self.index]

        # Right shift by 11 bits
        y = y ^ y >> 11
        # Shift y left by 7 and take the bitwise and of 2636928640
        y = y ^ y << 7 & 2636928640
        # Shift y left by 15 and take the bitwise and of y and 4022730752
        y = y ^ y << 15 & 4022730752
        # Right shift by 18 bits
        y = y ^ y >> 18

        self.index = self.index + 1

        return self._int32(y)

    def twist(self):
        for i in range(624):
            # Get the most significant bit and add it to the less significant
            # bits of the next number
            y = self._int32(
                (self.mt[i] & 0x80000000) +
                (self.mt[(i + 1) % 624] & 0x7fffffff)
            )
            self.mt[i] = self.mt[(i + 397) % 624] ^ y >> 1

            if y % 2 != 0:
                self.mt[i] = self.mt[i] ^ 0x9908b0df
        self.index = 0


class TwoPingMicro:
    debug = False
    ipv6 = False  # Not supported on all MicroPython platforms
    host = '0.0.0.0'
    port = 15998
    program_version = b'2ping MicroPython'
    led = False
    led_pin = 2
    led_swapped = True
    _mt = None
    _sock = None
    _reply_packet = bytearray(128)
    _led_pin_obj = None
    _led_off = None
    _led_on = None

    def __init__(self, config=None):
        if config is not None:
            for (k, v) in config.items():
                setattr(self, k, v)

        # MicroPython ESP8266 (and several other platforms) have urandom
        # available, but not all platforms do.  If urandom is not available,
        # use a Mersenne Twister RNG.
        try:
            self.urandom = os.urandom
        except:
            self.urandom = self.mturandom

        # Blink the LED when a packet is being processed
        if self.led:
            import machine
            self._led_pin_obj = machine.Pin(self.led_pin, machine.Pin.OUT)
            if self.led_swapped:
                self._led_off = self._led_pin_obj.on
                self._led_on = self._led_pin_obj.off
            else:
                self._led_off = self._led_pin_obj.off
                self._led_on = self._led_pin_obj.on
            self._led_off()

    def mturandom(self, b):
        out = bytearray(b)
        if self._mt is None:
            self._mt = MT19937(int(time.time()))
        for i in range(int(b / 4)):
            out[(i*4):(i*4+4)] = struct.pack('!I', self._mt.extract_number())
        remainder = b % 4
        if remainder == 3:
            out[-3:] = struct.pack('!I', self._mt.extract_number())[1:]
        elif remainder == 2:
            out[-2:] = struct.pack('!H', self._mt.extract_number() % 65536)
        elif remainder == 1:
            out[-1:] = struct.pack('!B', self._mt.extract_number() % 256)
        return(bytes(out))

    def parse_packet(self, packet):
        if self.debug:
            print('Packet length:', len(packet))

        # Magic number
        if packet[0:2] != b'\x32\x50':
            return

        # Validate checksum if present
        packet_checksum = struct.unpack_from('!H', packet, 2)[0]
        if packet_checksum != 0:
            packet_zeroed = memoryview(b'\x32\x50\x00\x00' + packet[4:])
            if twoping_checksum(packet_zeroed) != packet_checksum:
                if self.debug:
                    print('Invalid checksum')
                return
            if self.debug:
                print('Valid checksum')

        message_id = packet[4:10]
        if self.debug:
            print('Message ID:', bytes(message_id))
        opcode_flags = struct.unpack_from('!H', packet, 10)[0]
        if self.debug:
            print('Opcode flags:', opcode_flags)

        # We don't care unless a reply is requested
        if not (opcode_flags & 0x0001):
            if self.debug:
                print('No reply requested')
            return

        reply_message_id = self.urandom(6)
        if self.debug:
            print('Replying with message ID:', reply_message_id)

        # Zero out the reply packet buffer
        for i in range(len(self._reply_packet)):
            self._reply_packet[i] = 0

        self._reply_packet[0:2] = b'\x32\x50'  # magic number
        # [2:4] = checksum (currently zeroed)
        self._reply_packet[4:10] = reply_message_id
        self._reply_packet[10:12] = b'\x80\x02'  # 0x0002 + 0x8000

        # Opcode 0x0002 (In Reply To)
        self._reply_packet[12:14] = b'\x00\x06'
        self._reply_packet[14:20] = message_id

        # Opcode 0x8000 (Extended) + ExtID 0x3250564e (Program version)
        # Not strictly needed, but nice to advertise
        program_version_len = len(self.program_version)
        self._reply_packet[20:22] = bytes([0x00, 4+2+program_version_len])
        self._reply_packet[22:26] = b'\x32\x50\x56\x4e'
        self._reply_packet[26:28] = bytes([0x00, program_version_len])
        self._reply_packet[28:(28+program_version_len)] = self.program_version

        # Checksum is not strictly needed according to the protocol,
        # but easy to do
        struct.pack_into(
            '!H', self._reply_packet, 2, twoping_checksum(self._reply_packet)
        )

        return(self._reply_packet)

    def run(self):
        if self.ipv6:
            self._sock = socket.socket(socket.AF_INET6, socket.SOCK_DGRAM)
        else:
            self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.bind(socket.getaddrinfo(self.host, self.port)[0][-1])

        gc.collect()
        while True:
            (data, peer_address) = self._sock.recvfrom(1024)
            if self.led:
                self._led_on()
            if self.debug:
                print()
                print('Peer address:', peer_address)
            try:
                reply_packet = self.parse_packet(memoryview(data))
            except:
                raise
                continue
            if reply_packet:
                self._sock.sendto(reply_packet, peer_address)
            if self.led:
                self._led_off()

    def close(self):
        if self._sock is not None:
            self._sock.close()
            self._sock = None
            gc.collect()


def main(config=None):
    tp = TwoPingMicro(config)
    try:
        tp.run()
    except KeyboardInterrupt:
        tp.close()


if __name__ == '__main__':
    main({'debug': True})
