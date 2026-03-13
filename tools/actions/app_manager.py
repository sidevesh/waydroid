# Copyright 2021 Erfan Abdi
# SPDX-License-Identifier: GPL-3.0-or-later
import logging
import os
import shutil
import time
import tools.config
import tools.helpers.props
import tools.helpers.ipc
from tools.interfaces import IPlatform
from tools.interfaces import IStatusBarService
import dbus

def install(args):
    try:
        tools.helpers.ipc.DBusSessionService()

        cm = tools.helpers.ipc.DBusContainerService()
        session = cm.GetSession()
        if session["state"] == "FROZEN":
            cm.Unfreeze()

        tmp_dir = tools.config.session_defaults["waydroid_data"] + "/waydroid_tmp"
        if not os.path.exists(tmp_dir):
            os.makedirs(tmp_dir)

        shutil.copyfile(args.PACKAGE, tmp_dir + "/base.apk")
        platformService = IPlatform.get_service(args)
        if platformService:
            platformService.installApp("/data/waydroid_tmp/base.apk")
        else:
            logging.error("Failed to access IPlatform service")
        os.remove(tmp_dir + "/base.apk")

        if session["state"] == "FROZEN":
            cm.Freeze()
    except (dbus.DBusException, KeyError):
        logging.error("WayDroid session is stopped")

def remove(args):
    try:
        tools.helpers.ipc.DBusSessionService()

        cm = tools.helpers.ipc.DBusContainerService()
        session = cm.GetSession()
        if session["state"] == "FROZEN":
            cm.Unfreeze()

        platformService = IPlatform.get_service(args)
        if platformService:
            ret = platformService.removeApp(args.PACKAGE)
            if ret != 0:
                logging.error("Failed to uninstall package: {}".format(args.PACKAGE))
        else:
            logging.error("Failed to access IPlatform service")

        if session["state"] == "FROZEN":
            cm.Freeze()
    except dbus.DBusException:
        logging.error("WayDroid session is stopped")

def _read_varint(data, pos):
    result, shift = 0, 0
    while pos < len(data):
        b = data[pos]; pos += 1
        result |= (b & 0x7F) << shift
        if not (b & 0x80):
            break
        shift += 7
    return result, pos

def _read_android_persist_prop(work_dir, prop_name, default=""):
    """Read a persistent Android property directly from the data partition.

    Android 8+ stores persist.* properties in a protobuf-encoded file at
    <work>/data/property/persistent_properties.  This lets us check the
    property value even when the waydroid session is not running.
    """
    prop_file = os.path.join(work_dir, "data", "property", "persistent_properties")
    if not os.path.isfile(prop_file):
        return default
    try:
        with open(prop_file, "rb") as f:
            data = f.read()
        pos = 0
        while pos < len(data):
            tag, pos = _read_varint(data, pos)
            wire_type, field_num = tag & 0x7, tag >> 3
            if wire_type == 2:
                length, pos = _read_varint(data, pos)
                record = data[pos:pos + length]
                pos += length
                if field_num != 1:
                    continue
                # Parse PersistentPropertyRecord: field 1 = name, field 2 = value
                name, value, rpos = None, None, 0
                while rpos < len(record):
                    rtag, rpos = _read_varint(record, rpos)
                    rwire, rfield = rtag & 0x7, rtag >> 3
                    if rwire == 2:
                        rlen, rpos = _read_varint(record, rpos)
                        rval = record[rpos:rpos + rlen]
                        rpos += rlen
                        if rfield == 1:
                            name = rval.decode("utf-8", errors="replace")
                        elif rfield == 2:
                            value = rval.decode("utf-8", errors="replace")
                    elif rwire == 0:
                        _, rpos = _read_varint(record, rpos)
                    elif rwire == 1:
                        rpos += 8
                    elif rwire == 5:
                        rpos += 4
                    else:
                        break
                if name == prop_name:
                    return value if value is not None else default
            elif wire_type == 0:
                _, pos = _read_varint(data, pos)
            elif wire_type == 1:
                pos += 8
            elif wire_type == 5:
                pos += 4
            else:
                break
    except Exception:
        pass
    return default

def maybeLaunchLater(args, launchNow, background=False):
    try:
        tools.helpers.ipc.DBusSessionService()
        try:
            tools.helpers.ipc.DBusContainerService().Unfreeze()
        except:
            logging.error("Failed to unfreeze container. Trying to launch anyways...")
        launchNow()
    except dbus.DBusException:
        logging.error("Starting waydroid session")
        tools.actions.session_manager.start(args, launchNow, background=background)

def launch(args):
    cfg = tools.config.load(args)
    show_boot_animation = cfg["waydroid"].get("multi_windows_show_boot_animation", "False") == "True"
    multi_windows = _read_android_persist_prop(args.work, "persist.waydroid.multi_windows", "false")
    background = show_boot_animation and multi_windows != "false"
    def justLaunch():
        platformService = IPlatform.get_service(args)
        if platformService:
            platformService.setprop("waydroid.active_apps", args.PACKAGE)
            platformService.launchApp(args.PACKAGE)
            multiwin = platformService.getprop(
                "persist.waydroid.multi_windows", "false")
            if multiwin == "false":
                platformService.settingsPutString(
                    2, "policy_control", "immersive.status=*")
            else:
                platformService.settingsPutString(
                    2, "policy_control", "immersive.full=*")
        else:
            logging.error("Failed to access IPlatform service")
    maybeLaunchLater(args, justLaunch, background)

def list(args):
    try:
        tools.helpers.ipc.DBusSessionService()

        cm = tools.helpers.ipc.DBusContainerService()
        session = cm.GetSession()
        if session["state"] == "FROZEN":
            cm.Unfreeze()

        platformService = IPlatform.get_service(args)
        if platformService:
            appsList = platformService.getAppsInfo()
            for app in appsList:
                print("Name: " + app["name"])
                print("packageName: " + app["packageName"])
                print("categories:")
                for cat in app["categories"]:
                    print("\t" + cat)
        else:
            logging.error("Failed to access IPlatform service")

        if session["state"] == "FROZEN":
            cm.Freeze()
    except dbus.DBusException:
        logging.error("WayDroid session is stopped")

def showFullUI(args):
    def justShow():
        platformService = IPlatform.get_service(args)
        if platformService:
            platformService.setprop("waydroid.active_apps", "Waydroid")
            platformService.settingsPutString(2, "policy_control", "null*")
            # HACK: Refresh display contents
            statusBarService = IStatusBarService.get_service(args)
            if statusBarService:
                statusBarService.expand()
                time.sleep(0.5)
                statusBarService.collapse()
        else:
            logging.error("Failed to access IPlatform service")
    maybeLaunchLater(args, justShow)

def intent(args):
    cfg = tools.config.load(args)
    show_boot_animation = cfg["waydroid"].get("multi_windows_show_boot_animation", "False") == "True"
    multi_windows = _read_android_persist_prop(args.work, "persist.waydroid.multi_windows", "false")
    background = show_boot_animation and multi_windows != "false"
    def justLaunch():
        platformService = IPlatform.get_service(args)
        if platformService:
            ret = platformService.launchIntent(args.ACTION, args.URI)
            if ret == "":
                return
            pkg = ret if ret != "android" else "Waydroid"
            platformService.setprop("waydroid.active_apps", pkg)
            multiwin = platformService.getprop(
                "persist.waydroid.multi_windows", "false")
            if multiwin == "false":
                platformService.settingsPutString(
                    2, "policy_control", "immersive.status=*")
            else:
                platformService.settingsPutString(
                    2, "policy_control", "immersive.full=*")
        else:
            logging.error("Failed to access IPlatform service")
    maybeLaunchLater(args, justLaunch, background)
