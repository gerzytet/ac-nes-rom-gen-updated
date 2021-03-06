#!/usr/bin/env python
import argparse
import binascii
import gci
import pkg_resources
from .util import (block_count, block_align,
                   pack_short, pack_int, calcsum_byte,
                   yaz0_size)
from .tag_info import TagInfoGenerator
from .bigpatch import BigPatchGenerator

# Memory card block size
BLOCK_SZ = 0x2000

ZELDA_FREE = 0x806D4B9C
LOADER_ADDR = 0x80003970

MULTI_LOADER = pkg_resources.resource_stream(
    pkg_resources.Requirement.parse('ac_nesrom_gen'),
    'data/loader.bin'
).read()

BLANK_GCI_FILE = pkg_resources.resource_filename(
    pkg_resources.Requirement.parse('ac_nesrom_gen'),
    'data/blank.gci'
)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('game_name', type=str,
                        help='Game name displayed in NES Console menu')
    parser.add_argument('rom_file', type=str, help='NES ROM image')
    parser.add_argument('out_file', type=str, help='Output GCI')
    parser.add_argument('-l', '--loader', action='store_true', default=False,
                        help='Insert patch loader to read '
                             'big patches from ROM data')
    parser.add_argument('--autoheader', type=str,
                        help='Automatically generate a loader header for an '
                        'executable big patch. Takes target address of the '
                        'patch.')
    parser.add_argument('--banner', type=str, help='Save banner')
    parser.add_argument('-p', '--patch', action='append', nargs=2,
                        metavar=('address', 'bytes'),
                        help="""Hex encoded patch prefixed with location.
                        Multiple patches are allowed. Max size of each payload
                        is 251.""")
    parser.add_argument('-y', '--yaml', type=str,
                        help="""Load YAML description of
                        a series of big patches with settings""")

    args = parser.parse_args()

    blank_gci = gci.read_gci(BLANK_GCI_FILE)

    comments_addr = blank_gci['m_gci_header']['CommentsAddr']

    # Load ROM file
    romfile = open(args.rom_file, 'rb').read()

    if args.autoheader:
        args.loader = True
        auto_target = int(args.autoheader, 16)
        bpg = BigPatchGenerator()
        bpg.add_patch(auto_target, 1, romfile)
        romfile = bpg.compile()
    elif args.yaml:
        args.loader = True
        bpg = BigPatchGenerator()
        bpg.load_yaml(args.yaml)
        romfile = bpg.compile()

    if romfile[0:4] == 'Yaz0' and not args.loader:
        # If it's Yaz0 compressed get the size int from header
        nes_rom_len = block_align(yaz0_size(romfile), 16)
    else:
        nes_rom_len = block_align(len(romfile), 16)

    # Load banner file
    banner_len = 0x0
    banner_file = None
    if args.banner is not None:
        banner_file = open(args.banner, 'rb').read()
        banner_len = len(banner_file)

    # Tag info
    tig = TagInfoGenerator()

    # Insert loader
    if args.loader:
        print('Inserting loader')
        tig.add_patch(LOADER_ADDR, MULTI_LOADER)
        tig.add_patch(ZELDA_FREE, pack_int(LOADER_ADDR))

    if args.patch is not None:
        print('Inserting %u patches') % (len(args.patch))
        for patch in args.patch:
            patch_target = int(patch[0], 16)
            patch_payload = binascii.unhexlify(patch[1])
            print(patch)
            tig.add_patch(patch_target, patch_payload)

    tag_info = tig.compile()
    tag_info_len = len(tag_info)

    total_len = 0x660 + nes_rom_len + banner_len + tag_info_len

    new_count = max(1, block_count(total_len, BLOCK_SZ))
    print('Need %u blocks to contain ROM GCI' % (new_count))

    blank_gci['m_gci_header']['Filename'] = 'DobutsunomoriP_F_%s' % (
        (args.game_name[0:4]).upper())
    blank_gci['m_gci_header']['BlockCount'] = new_count

    # Copy beginning of NES SAVE file (includes save icon, game name)
    old_data = blank_gci['m_save_data']
    new_data_tmp = bytearray(BLOCK_SZ * new_count)
    new_data_tmp[0:0x640] = old_data[0][0:0x640]

    # Set description to name of the game
    new_data_tmp[comments_addr+32:comments_addr+64] = bytes(('%s ] ROM ' % (
        args.game_name)).ljust(32), 'ascii')

    # Set title of game as shown in game menu
    new_data_tmp[0x640:0x650] = bytes('ZZ%s' % (args.game_name.ljust(16)), 'ascii')

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

    # Calculate checksum
    checkbyte = calcsum_byte(new_data_tmp, verbose=True)
    new_data_tmp[(BLOCK_SZ * new_count)-1] = checkbyte
    
    blank_gci['m_save_data'] = [bytes(new_data_tmp)]
    with open(args.out_file, 'wb') as outfile:
        data = gci.write_gci(blank_gci)
        outfile.write(data)


if __name__ == '__main__':
    main()
