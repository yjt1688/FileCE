"""生成 FileCE 应用图标（app.ico）—— 纯几何绘制 + 4x 超采样抗锯齿

体积策略：小尺寸（≤64）用传统 DIB（Win7 加载最快、兼容性最好），
大尺寸（128/256）用 PNG 压缩 —— 一张 128×128 未压缩 DIB 就要 67KB，
换成 PNG 后只剩几 KB，整份 ico 从 100KB 降到 ~40KB。
PNG 图标自 Vista 起被 shell 支持，Win7 SP1+ 没问题。
"""
import struct, os, zlib

SS = 4  # 超采样倍数

def rounded_rect(x, y, w, h, r, px, py):
    if px < x or px >= x + w or py < y or py >= y + h:
        return False
    cx = min(max(px, x + r), x + w - r)
    cy = min(max(py, y + r), y + h - r)
    dx, dy = px - cx, py - cy
    return dx * dx + dy * dy <= r * r

def folder_shape(px, py, s):
    """白色文件夹：底托 + 标签页"""
    # 标签（左上小凸起）
    if rounded_rect(0.14*s, 0.30*s, 0.34*s, 0.14*s, 0.04*s, px, py):
        return True
    # 主体
    if rounded_rect(0.10*s, 0.38*s, 0.80*s, 0.36*s, 0.06*s, px, py):
        return True
    return False

def arrow_shape(px, py, s):
    """右下角向上箭头（速度感）"""
    cx, cy = 0.70*s, 0.68*s
    # 竖杆
    if abs(px - cx) <= 0.045*s and cy - 0.20*s <= py <= cy + 0.06*s:
        return True
    # 箭头
    t = (py - (cy - 0.22*s)) / (0.13*s)
    if 0 <= t <= 1:
        half = (1 - t) * 0.13*s
        if abs(px - cx) <= half:
            return True
    return False

def render(size):
    s = size
    px = bytearray(s * s * 4)
    n = s * SS
    for y in range(s):
        for x in range(s):
            r = g = b = a = 0
            for sy in range(SS):
                for sx in range(SS):
                    fx = (x * SS + sx + 0.5) / SS
                    fy = (y * SS + sy + 0.5) / SS
                    inside = rounded_rect(0, 0, s, s, 0.20 * s, fx, fy)
                    if not inside:
                        continue
                    # 背景：橙色渐变
                    t = fy / s
                    br = int(246 - 34 * t)
                    bg_ = int(140 - 34 * t)
                    bb = int(46 - 20 * t)
                    cr, cg, cb = br, bg_, bb
                    if folder_shape(fx, fy, s):
                        cr, cg, cb = 255, 255, 255
                    if arrow_shape(fx, fy, s):
                        cr, cg, cb = 255, 236, 210
                    r += cr; g += cg; b += cb; a += 255
            tot = SS * SS
            if a == 0:
                continue
            cov = a / tot
            i = (y * s + x) * 4
            px[i + 0] = min(255, int(b / (a / 255)))
            px[i + 1] = min(255, int(g / (a / 255)))
            px[i + 2] = min(255, int(r / (a / 255)))
            px[i + 3] = int(cov)
    return bytes(px)

def bmp_for_ico(size):
    """ICO 内嵌 DIB：BITMAPINFOHEADER + BGRA(bottom-up) + AND mask"""
    px = render(size)
    hdr = struct.pack('<IiiHHIIiiII', 40, size, size * 2, 1, 32, 0,
                      size * size * 4, 0, 0, 0, 0)
    # bottom-up 行序
    rows = []
    for y in range(size - 1, -1, -1):
        rows.append(px[y * size * 4:(y + 1) * size * 4])
    xor = b''.join(rows)
    # AND 掩码：1bit，行按 4 字节对齐
    stride = ((size + 31) // 32) * 4
    andmask = b'\x00' * (stride * size)
    return hdr + xor + andmask

def png_for_ico(size):
    """ICO 内嵌 PNG：32 位 RGBA、colortype 6，行前加 filter 字节 0"""
    px = render(size)
    def chunk(tag, data):
        body = tag + data
        return struct.pack('>I', len(data)) + body + struct.pack('>I', zlib.crc32(body) & 0xFFFFFFFF)
    raw = b''.join(b'\x00' + px[y * size * 4:(y + 1) * size * 4] for y in range(size))
    ihdr = struct.pack('>IIBBBBB', size, size, 8, 6, 0, 0, 0)
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', ihdr)
            + chunk(b'IDAT', zlib.compress(raw, 9)) + chunk(b'IEND', b''))


sizes = [16, 24, 32, 48, 64, 128, 256]
imgs = [bmp_for_ico(s) if s <= 32 else png_for_ico(s) for s in sizes]

out = struct.pack('<HHH', 0, 1, len(sizes))
offset = 6 + 16 * len(sizes)
entries = b''
for s, data in zip(sizes, imgs):
    entries += struct.pack('<BBBBHHII', s if s < 256 else 0, s if s < 256 else 0,
                           0, 0, 1, 32, len(data), offset)
    offset += len(data)
out += entries + b''.join(imgs)

path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'app.ico')
open(path, 'wb').write(out)
print('app.ico written:', len(out), 'bytes,', len(sizes), 'sizes')
