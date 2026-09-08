import struct
import sys
from pathlib import Path

data = Path(sys.argv[1]).read_bytes()
pe = struct.unpack_from('<I', data, 0x3c)[0]
count = struct.unpack_from('<H', data, pe + 6)[0]
opt_size = struct.unpack_from('<H', data, pe + 20)[0]
opt = pe + 24
sections = [struct.unpack_from('<8sIIII', data, opt + opt_size + i * 40) for i in range(count)]

def offset(rva):
    for _, size, va, raw_size, raw in sections:
        if va <= rva < va + max(size, raw_size):
            return raw + rva - va
    raise ValueError(hex(rva))

def string(rva):
    at = offset(rva)
    return data[at:data.index(b'\0', at)].decode(errors='replace')

imp = struct.unpack_from('<I', data, opt + 120)[0]
pos = offset(imp)
while True:
    lookup, _, _, name, iat = struct.unpack_from('<IIIII', data, pos)
    if not name:
        break
    index = 0
    while True:
        entry = struct.unpack_from('<Q', data, offset(lookup or iat) + index * 8)[0]
        if not entry:
            break
        if not entry >> 63:
            print(f'IAT {iat + index * 8:08x} {string(name)}!{string(entry + 2)}')
        index += 1
    pos += 20

exp = struct.unpack_from('<I', data, opt + 112)[0]
if exp:
    fields = struct.unpack_from('<IIHHIIIIIII', data, offset(exp))
    _, _, _, _, _, base, nfunc, nname, funcs, names, ords = fields
    symbols = []
    for i in range(nname):
        name = string(struct.unpack_from('<I', data, offset(names) + i * 4)[0])
        ordinal = struct.unpack_from('<H', data, offset(ords) + i * 2)[0]
        addr = struct.unpack_from('<I', data, offset(funcs) + ordinal * 4)[0]
        symbols.append((addr, name))
    symbols.sort()
    for arg in sys.argv[2:]:
        target = int(arg, 16)
        previous = [s for s in symbols if s[0] <= target]
        if previous:
            addr, name = previous[-1]
            print(f'NEAREST {target:x} {name}+0x{target - addr:x} (export RVA {addr:x}; nearest export only)')
