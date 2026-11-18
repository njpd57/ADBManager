import os
import struct
import tempfile
import unittest
import zipfile

from adbmanager import apps, backup, devices, icons, shell, system
from adbmanager.adb import AdbError, human_size, parse_devices


class ParseDevicesTest(unittest.TestCase):
    def test_parses_devices_l(self):
        out = ("List of devices attached\n"
               "R58M123ABC             device usb:1-1 product:x model:Pixel_7 device:panther\n"
               "192.168.1.5:5555       unauthorized\n"
               "* daemon started successfully\n")
        found = parse_devices(out)
        self.assertEqual([d.serial for d in found], ["R58M123ABC", "192.168.1.5:5555"])
        self.assertEqual(found[0].label, "Pixel_7 (R58M123ABC)")
        self.assertEqual(found[1].label, "192.168.1.5:5555 [unauthorized]")


class GetpropTest(unittest.TestCase):
    def test_parse_getprop(self):
        props = devices.parse_getprop("[ro.product.model]: [Pixel 7]\n[empty]: []\njunk\n")
        self.assertEqual(props, {"ro.product.model": "Pixel 7", "empty": ""})


class SystemTest(unittest.TestCase):
    def test_battery(self):
        out = "Current Battery Service state:\n  level: 87\n  status: 2\n  temperature: 301\n"
        battery = system.parse_battery(out)
        self.assertEqual(battery["level"], "87")
        self.assertEqual(battery["status"], "charging")
        self.assertEqual(battery["temperature"], "30.1 °C")

    def test_df(self):
        out = ("Filesystem 1K-blocks Used Available Use% Mounted on\n"
               "/dev/block/dm-9 1000 400 600 40% /data\n")
        usage = system.parse_df(out)
        self.assertEqual((usage.total, usage.used, usage.free),
                         (1000 * 1024, 400 * 1024, 600 * 1024))

    def test_meminfo(self):
        usage = system.parse_meminfo("MemTotal: 4000 kB\nMemAvailable: 1000 kB\n")
        self.assertEqual((usage.total, usage.free, usage.used),
                         (4000 * 1024, 1000 * 1024, 3000 * 1024))

    def test_ps_sorted_by_rss(self):
        out = "PID USER RSS NAME\n1 root 100 init\n2 u0_a1 900 app\n"
        rows = system.parse_ps(out)
        self.assertEqual([r[3] for r in rows], ["app", "init"])

    def test_ip_addresses(self):
        out = ("1: lo: <LOOPBACK> mtu 65536\n    inet 127.0.0.1/8 scope host lo\n"
               "2: wlan0: <UP> mtu 1500\n    inet 192.168.1.9/24 brd x scope global wlan0\n")
        self.assertEqual(system.parse_ip_addresses(out), [("wlan0", "192.168.1.9/24")])


class AppsTest(unittest.TestCase):
    def test_parse_packages(self):
        self.assertEqual(apps.parse_packages("package:b.app\npackage:a.app\n\n"), ["a.app", "b.app"])

    def test_parse_package_paths(self):
        out = "package:/data/app/x/base.apk\npackage:/data/app/x/split_a.apk\n"
        self.assertEqual(len(apps.parse_package_paths(out)), 2)

    def test_check_success(self):
        self.assertEqual(apps._check_success("Success\n"), "Success")
        with self.assertRaises(AdbError):
            apps._check_success("Failure [INSTALL_FAILED_OLDER_SDK]")

    def test_collect_apks_from_bundle_and_zip_slip(self):
        with tempfile.TemporaryDirectory() as tmp:
            bundle = os.path.join(tmp, "app.xapk")
            with zipfile.ZipFile(bundle, "w") as z:
                z.writestr("base.apk", "x")
                z.writestr("manifest.json", "{}")
            work = os.path.join(tmp, "work")
            os.mkdir(work)
            self.assertEqual([os.path.basename(p) for p in apps.collect_apks(bundle, work)],
                             ["base.apk"])
            evil = os.path.join(tmp, "evil.zip")
            with zipfile.ZipFile(evil, "w") as z:
                z.writestr("../escape.apk", "x")
            with self.assertRaises(AdbError):
                apps.collect_apks(evil, work)


class AppInfoTest(unittest.TestCase):
    def test_diskstats(self):
        out = "\n".join(['Package Names: ["a.app","b.app"]', "App Sizes: [100,200]",
                         "App Data Sizes: [10,20]", "Cache Sizes: [1]"])
        self.assertEqual(apps.parse_diskstats(out), {"a.app": (100, 10, 1), "b.app": (200, 20, 0)})

    def test_package_list_full(self):
        out = "\n".join(["package:/data/app/x/base.apk=com.x uid:10191",
                         "package:/system/app/Y.apk=com.y"])
        self.assertEqual(apps.parse_package_list_full(out),
                         {"com.x": ("/data/app/x/base.apk", "10191"),
                          "com.y": ("/system/app/Y.apk", "")})

    def test_package_details(self):
        out = "\n".join([
            "  Package [com.x] (abc):", "    versionName=1.2",
            "    lastUpdateTime=2026-01-02 03:04:05", "    installerPackageName=com.android.vending",
            "    User 0: installed=true stopped=false enabled=2 instant=false",
            "      firstInstallTime=2026-01-01 00:00:00",
            "  Package [com.y] (def):", "    installerPackageName=null"])
        details = apps.parse_package_details(out)
        self.assertEqual(details["com.x"]["installed"], "2026-01-01 00:00:00")
        self.assertEqual(details["com.x"]["installer"], "com.android.vending")
        self.assertFalse(details["com.x"]["enabled"])
        self.assertEqual(apps._clean_installer(details["com.y"]["installer"]), "")

    def test_total_size(self):
        self.assertEqual(apps.AppInfo("p", app_size=1, data_size=2, cache_size=3).total_size, 6)


class IconsTest(unittest.TestCase):
    def _pool(self, strings):
        blobs, offsets, pos = b"", [], 0
        for text in strings:
            raw = text.encode("utf-8")
            entry = bytes([len(text), len(raw)]) + raw + bytes(1)
            offsets.append(pos)
            blobs += entry
            pos += len(entry)
        header = 28 + 4 * len(strings)
        blobs += bytes(-len(blobs) % 4)
        head = struct.pack("<HHIIIIII", 1, 28, header + len(blobs), len(strings), 0, 1 << 8,
                           header, 0)
        return head + struct.pack(f"<{len(strings)}I", *offsets) + blobs

    def test_string_pool_utf8(self):
        data = self._pool(["res/mipmap/ic.png", "hello"])
        self.assertEqual(icons.parse_string_pool(data, 0), ["res/mipmap/ic.png", "hello"])

    def test_pick_icon_file_prefers_dense_png_over_xml(self):
        table = icons.ResourceTable.__new__(icons.ResourceTable)
        table.values = ["res/mipmap-mdpi/i.png", "res/mipmap-xxhdpi/i.png",
                        "res/mipmap-anydpi/i.xml"]
        table.entries = {0x7F020000: [(160, False, icons.TYPE_STRING, 0),
                                      (480, False, icons.TYPE_STRING, 1),
                                      (icons.DENSITY_ANY, False, icons.TYPE_STRING, 2)]}
        self.assertEqual(icons.pick_icon_file(table, 0x7F020000),
                         ["res/mipmap-xxhdpi/i.png", "res/mipmap-mdpi/i.png",
                          "res/mipmap-anydpi/i.xml"])


class ShellTest(unittest.TestCase):
    def test_logcat_args(self):
        self.assertEqual(shell.logcat_args("W"), ["logcat", "-v", "threadtime", "*:W"])
        self.assertEqual(shell.logcat_args("D", "MyTag"),
                         ["logcat", "-v", "threadtime", "MyTag:D", "*:S"])

    def test_line_matches(self):
        self.assertTrue(shell.line_matches("Hello World", "world"))
        self.assertFalse(shell.line_matches("Hello World", "world", case_sensitive=True))
        self.assertTrue(shell.line_matches("anything", ""))


class BackupTest(unittest.TestCase):
    def test_parse_permissions(self):
        out = ("    runtime permissions:\n"
               "      android.permission.CAMERA: granted=true, flags=[ USER_SET]\n"
               "      android.permission.RECORD_AUDIO: granted=false\n")
        self.assertEqual(backup.parse_permissions(out),
                         {"android.permission.CAMERA": True,
                          "android.permission.RECORD_AUDIO": False})


class HumanSizeTest(unittest.TestCase):
    def test_human_size(self):
        self.assertEqual(human_size(512), "512 B")
        self.assertEqual(human_size(2048), "2.0 KB")


if __name__ == "__main__":
    unittest.main()
