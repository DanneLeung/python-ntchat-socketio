# -*- coding: utf-8 -*-
import atexit
import json
import os
import sys
import time
import traceback
import shutil
import base64

import ntchat
import socketio
from ntchat.utils import logger

ROOT_DIR = "./upload"

log = logger.get_logger("Main")

wxbot = "ntchat"
host = "http://localhost:10086"
base_dir = ROOT_DIR
static_url = "http://localhost:8000/static"
short_root_url = "http://localhost:8000/docs"
# local storage mode
local_mode = True
# cache room names in memory
room_names = {}

global_quit_flag = False

sio = socketio.Client()


def send_sio_wx_message(msg):
    log.info("### send sio message : %s", json.dumps(msg))
    try:
        sio.emit("message", json.dumps(msg))
    except:
        traceback.print_exc()


def send_ping():
    sio.emit('ping')


@sio.event
def connect_error(data):
    log.error('connection error %s', data)


@sio.event
def disconnect():
    log.info('disconnected from server, reconnect ...')


@sio.event
def connect():
    log.info('connection established')
    send_ping()


@sio.event
def pong(data):
    sio.sleep(5)
    if sio.connected:
        send_ping()


@sio.on("welcome")
def on_welcome(data):
    log.info("connected with session id: %s.", data)


@sio.on("message")
def on_message(message):
    global base_dir
    data = json.loads(message)
    log.info("sio received message: %s.", data)
    wx_type = data.get("type")
    to_wxid = data.get("toUserId")
    room_wxid = data.get("roomId")
    text = data.get("text")
    if text:
        if room_wxid:
            # 群中发送@消息
            log.info("send at message, room_wxid: %s, to_wxid: %s", room_wxid, to_wxid)
            wechat.send_room_at_msg(room_wxid, text, [to_wxid])
        else:
            wechat.send_text(to_wxid, text)
    # 文本外没有@操作，群则发群消息
    if room_wxid:
        to_wxid = room_wxid

    path = data.get("path")
    str_base64 = data.get("base64")
    if path:
        if str_base64:
            # base64有文件内容
            path = base64_to_file(str_base64, path)
        else:
            # 本地文件模式
            path = base_dir + path  # if local_mode else (static_url + path)

        # path = os.path.join(base_dir, path)
        if not path or not os.path.exists(path):
            log.error("error while sending file, file not found: %s", path)

        if wx_type == 'image':
            wechat.send_image(to_wxid, path)
        elif wx_type == 'file':
            ok = wechat.send_file(to_wxid, path)
            if not ok:
                wechat.send_link_card(to_wxid, title=data.get("fileName"), url=short_root_url + data.get("docId"))
    if wx_type == 'url' and data.get("url"):
        url = data.get("url")
        wechat.send_link_card(to_wxid, title="" if data.get("title") is None else data.get("title"), url=url, desc="" if data.get("description") is None else data.get("description"),
                              image_url=data.get("thumbnailUrl"))


# 微信进程hook通知
def on_wechat_ready(wechat_instace: ntchat.WeChat, message):
    log.info("on_wechat_ready: % ", json.dumps(message))
    pass


# 微信进程关闭通知
def on_wechat_quit(wechat_instace: ntchat.WeChat):
    global global_quit_flag
    global_quit_flag = True


def on_user_login(wechat_instance: ntchat.WeChat, message):
    data = message.get("data")
    wxid = data.get("wxid")
    account = data.get("account")
    avatar = data.get("avatar")
    nickname = data.get("nickname")
    phone = data.get("phone")
    pid = data.get("pid")

    # global base_dir
    # if not base_dir.endswith(wxid):
    #     base_dir = os.path.join(base_dir, wxid)
    log.info("base_dir: %s.", base_dir)

    msg = {"wxbot": wxbot, "id": wxid, "name": account, "avatar": avatar, "alias": nickname, "phone": phone, "localMode": local_mode}
    log.info("user login: %s.", json.dumps(msg))
    sio.emit("login", json.dumps(msg))


def on_user_logout(wechat_instance: ntchat.WeChat, message):
    log.info(json.dumps(message))


def on_receive_friend(wechat_instance: ntchat.WeChat, message):
    log.info(json.dumps(message))


def on_room_add_member(wechat_instance: ntchat.WeChat, message):
    log.info(json.dumps(message))


# 注册消息回调
def on_recv_text_msg(wechat_instance: ntchat.WeChat, message):
    data = message.get("data")
    self_wxid = wechat_instance.get_login_info().get("wxid")
    room_wxid = data.get("room_wxid")
    from_wxid = data.get("from_wxid")
    to_wxid = data.get("to_wxid")
    if to_wxid == room_wxid:
        to_wxid = self_wxid
    msgid = data.get("msgid")
    # "@"
    at_user_list = data.get("at_user_list")
    mention_self = (self_wxid in at_user_list)

    room_name = get_room_name(wechat_instance, room_wxid)

    text = data.get("msg")
    msg = {"wxbot": wxbot, "msgId": msgid, "roomId": room_wxid, "roomName": room_name, "fromUserId": from_wxid, "toUserId": to_wxid, "type": "text", "mentionSelf": mention_self, "text": text}
    #
    # # 判断消息不是自己发的并且不是群消息时，回复对方
    if from_wxid != self_wxid:
        send_sio_wx_message(msg)


def on_recv_image_msg(wechat_instance: ntchat.WeChat, message):
    data = message.get("data")
    self_wxid = wechat_instance.get_login_info().get("wxid")
    room_wxid = data.get("room_wxid")
    from_wxid = data.get("from_wxid")
    to_wxid = data.get("to_wxid")
    if to_wxid == room_wxid:
        to_wxid = self_wxid
    msgid = data.get("msgid")

    image = data.get("image")
    xor_key = data.get("xor_key")

    room_name = get_room_name(wechat_instance, room_wxid)

    msg = {"wxbot": wxbot, "msgId": msgid, "roomId": room_wxid, "roomName": room_name, "fromUserId": from_wxid, "toUserId": to_wxid, "type": "image"}
    # 判断消息不是自己发的并且不是群消息时，回复对方
    if from_wxid != self_wxid:
        times = 0
        while times < 5:
            times = times + 1
            out = image_decode(image, msgid, xor_key)
            if out:
                log.info("save image file to %s.", out)
                msg["path"] = out
                if not local_mode:
                    msg[base64] = file_to_base64(os.path.join(base_dir, out))
                break

        if times < 5:
            send_sio_wx_message(msg)
        else:
            log.error("error while saveing image file %s", image)


def on_recv_file_msg(wechat_instance: ntchat.WeChat, message):
    data = message.get("data")
    self_wxid = wechat_instance.get_login_info().get("wxid")
    room_wxid = data.get("room_wxid")
    from_wxid = data.get("from_wxid")
    to_wxid = data.get("to_wxid")
    if to_wxid == room_wxid:
        to_wxid = self_wxid
    msgid = data.get("msgid")

    room_name = get_room_name(wechat_instance, room_wxid)

    msg = {"wxbot": wxbot, "msgId": msgid, "roomId": room_wxid, "roomName": room_name, "fromUserId": from_wxid, "toUserId": to_wxid, "type": "file"}

    file = data.get("file")
    # 判断消息不是自己发的并且不是群消息时，回复对方
    if from_wxid != self_wxid:
        # move file
        out = copy_file(file)
        if out:
            log.info("save attach file to %s.", out)
            msg["path"] = out
            msg["fileName"] = os.path.basename(file)
            if not local_mode:
                msg[base64] = file_to_base64(os.path.join(base_dir, out))
            send_sio_wx_message(msg)


def get_room_name(wechat: ntchat.WeChat, room_wxid):
    try:
        room_name = room_names.get(room_wxid)
        if not room_name:
            room_name = wechat.get_room_name(room_wxid)
            room_names[room_wxid] = room_name
        return room_name
    except:
        traceback.print_exc()


# 文件转base64
def file_to_base64(file_path):
    with open(file_path, 'rb') as f:
        a_bytes = f.read()
        str_base64 = base64.b64encode(a_bytes).decode('utf8')
        return str_base64


# base64 保存
def base64_to_file(str_base64, file_path):
    a_bytes = base64.b64decode(str_base64)
    with open(file_path, 'wb') as f:
        f.write(a_bytes)
        return file_path


def copy_file(data_path):
    global base_dir
    # 目标目录
    dest_path = os.path.join("file", time.strftime("%Y-%m-%d"))
    # 目录不存在，创建
    if not os.path.exists(os.path.join(base_dir, dest_path)):
        os.makedirs(os.path.join(base_dir, dest_path))
    file_name = os.path.basename(data_path)
    log.info("### file name %s", file_name)
    try:
        count = 0
        while not os.path.exists(data_path) and count < 5:
            count = count + 1
            time.sleep(1)
        if count >= 5:
            log.error("file not exists %s", data_path)
            return
        dest_path = os.path.join(dest_path, file_name)
        # 文件存在，跳过

        if os.path.exists(os.path.join(base_dir, dest_path)):
            return
        shutil.copyfile(data_path, os.path.join(base_dir, dest_path))
        return os.path.join(os.path.sep, dest_path)
    except:
        traceback.print_exc()


def image_decode(data_path, dest_file_name, xor_value):
    """

    :rtype: str 相对路径文件名
    """

    try:
        global base_dir
        log.info("decoding image %s.", data_path)
        # 目标目录
        dest_path = os.path.join("image", time.strftime("%Y-%m-%d"))
        # 目录不存在，创建
        if not os.path.exists(os.path.join(base_dir, dest_path)):
            os.makedirs(os.path.join(base_dir, dest_path))

        dest_file_name = dest_file_name + ".png"
        dest_path = os.path.join(dest_path, dest_file_name)

        # 检查源图片文件
        count = 0
        while not os.path.exists(data_path) and count < 5:
            count = count + 1
            time.sleep(1)
        if count >= 5:
            log.error("image file not found %s.", data_path)
            return

        dat_read = open(data_path, "rb")
        # 目标png图片文件
        png_write = open(os.path.join(base_dir, dest_path), "wb")

        for now in dat_read:
            for nowByte in now:
                new_byte = nowByte ^ xor_value
                png_write.write(bytes([new_byte]))
        dat_read.close()
        png_write.close()
        return os.path.join(os.path.sep, dest_path)
    except:
        traceback.print_exc()
        pass


def sys_exit():
    ntchat.exit_()
    sys.exit()


def init_wechat():
    wc = ntchat.WeChat()

    # 打开pc微信, smart: 是否管理已经登录的微信
    wc.open(smart=True)
    # 等待登录
    wc.wait_login()
    wc.on(ntchat.MT_READY_MSG, on_wechat_ready)
    wc.on(ntchat.MT_RECV_WECHAT_QUIT_MSG, on_wechat_quit)
    wc.on(ntchat.MT_USER_LOGIN_MSG, on_user_login)
    wc.on(ntchat.MT_USER_LOGOUT_MSG, on_user_logout)
    wc.on(ntchat.MT_RECV_FRIEND_MSG, on_receive_friend)
    wc.on(ntchat.MT_ROOM_ADD_MEMBER_NOTIFY_MSG, on_room_add_member)
    wc.on(ntchat.MT_RECV_TEXT_MSG, on_recv_text_msg)
    wc.on(ntchat.MT_RECV_IMAGE_MSG, on_recv_image_msg)
    wc.on(ntchat.MT_RECV_FILE_MSG, on_recv_file_msg)
    return wc


wechat: ntchat.WeChat = init_wechat()

if __name__ == '__main__':
    try:
        atexit.register(sys_exit)
        sio.connect(host, transports="websocket")
        sio.wait()

    except KeyboardInterrupt:
        ntchat.exit_()
        sys.exit()
    except:
        ntchat.exit_()
        sys.exit()
