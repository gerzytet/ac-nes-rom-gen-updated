#!/usr/bin/env python
import argparse
import binascii
import gci
import struct

# Memory card block size
BLOCK_SZ = 0x2000

# Patch loader patch by Cuyler36
CUYLER_LOADER_ADDR = 0x80003970
CUYLER_LOADER = binascii.unhexlify(
    "9421FFD07C0802A6"
    "900100209061001C"
    "9081001890A10014"
    "90C100103C60801F"
    "38636C6480630000"
    "2803000041820000"
    "8083000028040000"
    "4182000090810028"
    "80C3000890C10024"
    "80C3000490C1002C"
    "38A3000C2C060000"
    "4081001C88650000"
    "9864000038840001"
    "38A5000138C6FFFF"
    "4BFFFFE48081002C"
    "80610028548006FF"
    "4182000838840020"
    "3884001F5484D97E"
    "7C8903A67C001FAC"
    "7C001BAC38630020"
    "4200FFF47C0004AC"
    "4C00012C8061001C"
    "3CA0806260A5D4CC"
    "3CC0806D60C64B9C"
    "90A600007CA903A6"
    "4E80042180810024"
    "2804000041820014"
    "8081002880010020"
    "7C8803A64800000C"
    "800100207C0803A6"
    "8081001880A10014"
    "80C1001038210030"
    "4E80002000000000"
)

# - loads multiple big patches (one last one can be executable to auto-jump to)
# - uses a different calling convention for executable patches
CUYLER_MULTI_LOADER = binascii.unhexlify(
    "9421FFD07C0802A6"
    "900100349061001C"
    "9081001890A10014"
    "90C1001090E1000C"
    "3C60801F38636C64"
    "8063000028030000"
    "418200A880E30000"
    "3863000490610020"
    "4182009880610020"
    "8083000028040000"
    "4182008890810028"
    "80C3000890C10024"
    "80C3000490C1002C"
    "38A3000C2C060000"
    "4081001C88650000"
    "9864000038840001"
    "38A5000138C6FFFF"
    "4BFFFFE490A10020"
    "8081002C80610028"
    "548006FF41820008"
    "388400203884001F"
    "5484D97E7C8903A6"
    "7C001FAC7C001BAC"
    "386300204200FFF4"
    "7C0004AC4C00012C"
    "38E7FFFF28070000"
    "418200084BFFFF70"
    "8081002428040000"
    "4182001080810028"
    "7C8903A64E800421"
    "8061001C3CA08062"
    "60A5D4CC3CC0806D"
    "60C64B9C90A60000"
    "7CA903A64E800421"
    "800100347C0803A6"
    "8081001880A10014"
    "80C1001080E1000C"
    "382100304E800020"
)


def block_count(data_size, block_size):
    """The number of blocks of given size required to
    hold the data."""

    blocks = 0
    while (block_size * blocks) < data_size:
        blocks += 1

    return blocks


def block_align(data_size, block_size):
    """Return size of buffer that is a multiple of the
    block size that can contain the data."""
    return block_count(data_size, block_size) * block_size


def pack_byte(value):
    return struct.pack('>B', value)


def pack_short(value):
    return struct.pack('>H', value)


def pack_int(value):
    return struct.pack('>I', value)


def tag_header(tag, size):
    return struct.pack('>3sB', tag, size)


def create_pat(target_addr, payload):
    """Create a PAT tag that can patch data into any address
    between 0x80000000 and 0x807FFFFF.

    The maximum payload size is 255-4 = 251 bytes."""

    if len(payload) > 251:
        raise Exception('payload too big')

    # Calculate address bytes
    off_high = ((target_addr >> 16) & 0xFFFF) - 0x7F80
    off_low = target_addr & 0xFFFF

    tag_data = struct.pack('>BBH', off_high, len(payload), off_low) + payload
    tag_head = tag_header('PAT', len(tag_data))

    return tag_head + tag_data


def create_tag_buffer(tags):
    tag_info = tag_header('ZZZ', 0)  # ignored beginning
    tag_info += ''.join(tags)
    tag_info += tag_header('END', 0)

    return tag_info


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('game_name', type=str,
                        help='Game name displayed in NES Console menu')
    parser.add_argument('rom_file', type=str, help='NES ROM image')
    parser.add_argument('out_file', type=str, help='Output GCI')
    parser.add_argument('--loader', action='store_true', default=False,
                        help='Insert patch loader patch to read '
                             'big patches from ROM data')
    parser.add_argument('--autoheader', type=str,
                        help='Automatically generate a loader header for an '
                        'executable big patch')
    parser.add_argument('--banner', type=str, help='Save banner')
    parser.add_argument('-p', '--patch', action='append', nargs=2,
                        metavar=('address', 'bytes'),
                        help="""Hex encoded patch prefixed with location.
                        Multiple patches are allowed. Max size of each payload
                        is 251.""")
    args = parser.parse_args()

    blank_gci = gci.read_gci('blank.gci')

    comments_addr = blank_gci['m_gci_header']['CommentsAddr']

    # Load ROM file
    romfile = open(args.rom_file, 'rb').read()

    if args.autoheader:
        args.loader = True
        auto_target = int(args.autoheader, 16)
        loader_header = struct.pack('>IIII',
                                    1,  # number of patches
                                    auto_target,  # target address
                                    len(romfile),  # size of big patch
                                    1  # is executable
                                    )
        romfile = loader_header + romfile

    if romfile[0:4] == 'Yaz0' and not args.loader:
        # If it's Yaz0 compressed get the size int from header
        nes_rom_len = struct.unpack('>I', romfile[4:8])[0]
    else:
        nes_rom_len = len(romfile)

    # Load banner file
    banner_len = 0x0
    banner_file = None
    if args.banner is not None:
        banner_file = open(args.banner, 'rb').read()
        banner_len = len(banner_file)

    # Tag info
    tags = []

    # Insert loader
    if args.loader:
        print 'Inserting loader'
        loader_patch1 = create_pat(CUYLER_LOADER_ADDR,
                                   CUYLER_MULTI_LOADER[0:250])
        loader_patch2 = create_pat(CUYLER_LOADER_ADDR+250,
                                   CUYLER_MULTI_LOADER[250:])
        loader_jump = create_pat(0x806D4B9C, pack_int(0x80003970))
        tags.append(loader_patch1)
        tags.append(loader_patch2)
        tags.append(loader_jump)

    if args.patch is not None:
        print 'Inserting %u patches' % (len(args.patch))
        for patch in args.patch:
            patch_target = int(patch[0], 16)
            patch_payload = binascii.unhexlify(patch[1])
            print patch
            tags.append(create_pat(patch_target, patch_payload))

    tag_info = create_tag_buffer(tags)
    tag_info_len = len(tag_info)

    total_len = 0x660 + len(romfile) + banner_len + tag_info_len

    new_count = max(1, block_count(total_len, BLOCK_SZ))
    print 'Need %u blocks to contain ROM GCI' % (new_count)

    blank_gci['m_gci_header']['Filename'] = 'DobutsunomoriP_F_%s' % (
        (args.game_name[0:4]).upper())
    blank_gci['m_gci_header']['BlockCount'] = new_count

    # Copy beginning of NES SAVE file (includes save icon, game name)
    old_data = blank_gci['m_save_data']
    new_data_tmp = bytearray(BLOCK_SZ * new_count)
    new_data_tmp[0:0x640] = old_data[0][0:0x640]

    # Set description to name of the game
    new_data_tmp[comments_addr+32:comments_addr+64] = ('%s ] ROM ' % (
        args.game_name)).ljust(32)

    # Set title of game as shown in game menu
    new_data_tmp[0x640:0x650] = 'ZZ%s' % (args.game_name.ljust(16))

    # Uncompressed ROM size (0 for none) - divided by 16
    # Force it to be 0 so the ROM data isn't run
    new_data_tmp[0x640+0x12:0x640+0x14] = pack_short(nes_rom_len >> 4)

    # Tag info size
    new_data_tmp[0x640+0x14:0x640+0x16] = pack_short(tag_info_len)

    # Banner size (0 for none)
    new_data_tmp[0x640+0x1A:0x640+0x1C] = pack_short(banner_len)

    # Bit flags
    # high bit: use banner
    # 2 bits: text code (0-3)    default=1, fromcard=2
    # 2 bits: banner code (0-3)  default=1
    # 2 bits: icon code (0-3)    default=1
    new_data_tmp[0x640+0x1C] = 0b11001010

    # Bit flags
    # high bit: ?
    # 2 bits: banner format
    new_data_tmp[0x640+0x1D] = 0b00000000

    # Icon format
    new_data_tmp[0x640+0x16] = 0x00
    new_data_tmp[0x640+0x17] = 0x00

    # Unpacking order: tag info, Banner, NES Rom
    data_offset = 0x660

    # Copy in tag info
    if tag_info_len > 0:
        new_data_tmp[data_offset:data_offset+tag_info_len] = tag_info
        # align on 16 byte boundary
        data_offset += block_align(tag_info_len, 16)

    # Copy in banner
    if banner_len > 0:
        new_data_tmp[data_offset:data_offset+banner_len] = banner_file
        data_offset += block_align(banner_len, 16)

    # Copy in the NES ROM
    if nes_rom_len > 0:
        new_data_tmp[data_offset:data_offset+len(romfile)] = romfile

    checksum = 0
    for b in new_data_tmp:
        checksum += b & 0xFF
        checksum = checksum & 0xFFFFFFFF

    # Calculate checksum
    checkbyte = 256 - (checksum & 0xFF)
    new_data_tmp[(BLOCK_SZ * new_count)-1] = checkbyte

    print 'Checksum: 0x%08x' % (checksum)
    print 'Check byte: 0x%02x' % (checkbyte)

    # Save new GCI
    blank_gci['m_save_data'] = str(new_data_tmp)
    with open(args.out_file, 'wb') as outfile:
        data = gci.write_gci(blank_gci)
        outfile.write(data)


if __name__ == '__main__':
    main()