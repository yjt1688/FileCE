from PIL import Image, ImageDraw, ImageFont

FONT = "C:/Windows/Fonts/msyh.ttc"
def F(sz): return ImageFont.truetype(FONT, sz)

W, H = 1000, 640
img = Image.new("RGB", (W, H), "#ffffff")
d = ImageDraw.Draw(img)

# ---- title bar ----
d.rectangle([0,0,W,32], fill="#1f3a5f")
d.text((12,7), "FileCE", font=F(16), fill="#ffffff")
d.text((W-150,9), "—  □  ✕", font=F(13), fill="#cdd8e6")

# ---- menu bar ----
d.rectangle([0,32,W,58], fill="#f3f3f3")
for i,t in enumerate(["文件(F)","转到(G)","查看(V)","工具(T)","帮助(H)"]):
    d.text((12+i*70,39), t, font=F(13), fill="#222222")

# ---- toolbar ----
d.rectangle([0,58,W,94], fill="#e9eef3")
tb = ["上级","刷新","新建文件夹","剪切","复制","粘贴","删除","属性","筛选"]
x = 10
for t in tb:
    w = d.textlength(t, font=F(12)) + 16
    d.rectangle([x,64,x+w,88], fill="#ffffff", outline="#c2ccd6")
    d.text((x+8,69), t, font=F(12), fill="#222222")
    x += w + 6

# ---- body split ----
TREE_W = 250
d.rectangle([0,94,TREE_W,H-28], fill="#f7f7f7")
d.rectangle([TREE_W,94,W,H-28], fill="#ffffff")
# splitter
d.rectangle([TREE_W-2,94,TREE_W,H-28], fill="#d7dee6")

# tree header
d.rectangle([0,94,TREE_W,118], fill="#e9eef3")
d.text((10,100), "文件夹", font=F(13), fill="#333333")

# tree items
tree = [
 ("此电脑", 0, True),
 ("C:", 1, False),
 ("D:", 1, False),
 ("E:", 1, False),
 ("桌面", 1, False),
 ("文档", 1, False),
 ("下载", 1, False),
]
y = 124
for name, lvl, exp in tree:
    tx = 12 + lvl*18
    if lvl > 0:
        d.rectangle([tx-2,y+4,tx+8,y+14], outline="#9aa7b4", fill="#ffffff")
        if exp:
            d.line([tx+3,y+4,tx+3,y+14], fill="#9aa7b4")
            d.line([tx-2,y+9,tx+8,y+9], fill="#9aa7b4")
    icon = "💻" if name=="此电脑" else ("📁" if lvl>0 else "")
    # draw simple glyph boxes instead of emoji (PIL may lack emoji)
    d.text((tx+12, y+2), name, font=F(13), fill="#1a1a1a")
    y += 24

# list header
cols = [("名称",12,150),("类型",170,120),("大小",300,90),("属性",400,60),("修改时间",470,150),("创建时间",630,160)]
d.rectangle([TREE_W,94,W,118], fill="#e9eef3")
for name,cx,cw in cols:
    d.text((TREE_W+cx,100), name, font=F(12), fill="#333333")
d.line([TREE_W,118,W,118], fill="#d7dee6")

rows = [
 ("文档","文件夹","","","2026-11-06 10:23","2026-10-30 09:12"),
 ("图片","文件夹","","","2026-11-05 09:10","2026-10-12 14:01"),
 ("FileCE.exe","应用程序","241 KB","A","2026-11-08 10:54","2026-11-08 10:54"),
 ("报告.docx","Microsoft Word","38 KB","A","2026-11-02 15:40","2026-10-29 11:20"),
 ("数据.zip","压缩文件","1.2 MB","A","2026-10-28 11:05","2026-10-28 11:05"),
 ("日志.txt","文本文档","4 KB","A","2026-11-07 22:18","2026-11-01 08:33"),
 ("视频","文件夹","","","2026-10-15 18:30","2026-09-22 20:05"),
]
ry = 119
rh = (H-28-119)/len(rows)
for i,r in enumerate(rows):
    if i%2==1:
        d.rectangle([TREE_W,ry,TREE_W+W,ry+rh], fill="#f4f7fb")
    cy = ry + rh/2 - 8
    for (name,cx,cw),val in zip(cols, r):
        txt = str(val)
        # truncate
        while d.textlength(txt, font=F(12)) > cw-6 and len(txt)>1:
            txt = txt[:-1]
        if name=="名称" and r[1]=="文件夹":
            d.rectangle([TREE_W+cx+2,cy+3,TREE_W+cx+12,cy+13], outline="#e0b341", fill="#ffe08a")
        d.text((TREE_W+cx+ (16 if name=="名称" and r[1]=="文件夹" else 2), cy), txt, font=F(12), fill="#1a1a1a")
    ry += rh
d.line([TREE_W,118,TREE_W,H-28], fill="#d7dee6")

# ---- status bar ----
d.rectangle([0,H-28,W,H], fill="#e9eef3")
d.text((12,H-23), "已选中 0 个对象，共 7 项", font=F(12), fill="#333333")
d.text((W-140,H-23), "筛选: 关闭", font=F(12), fill="#333333")

img.save("docs/screenshot.png", "PNG")
print("saved docs/screenshot.png", img.size)
