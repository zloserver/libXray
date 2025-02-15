import os.path
import shutil
import subprocess

from app.build import Builder
from app.cmd import create_dir_if_not_exists, delete_dir_if_exists


# https://github.com/golang/mobile/blob/master/cmd/gomobile/build_darwin_test.go


class AppleTarget(object):
    def __init__(
        self, platform: str, go_arch: str, apple_arch: str, sdk: str, min_version: str
    ):
        self.platform = platform
        self.go_arch = go_arch
        self.apple_arch = apple_arch
        self.sdk = sdk
        self.min_version = min_version

class AppleStaticLib(object):
    def __init__(
        self, sdk: str, apple_archs: list[str]
    ):
        self.sdk = sdk
        self.apple_archs = apple_archs

    def lib_name(self) -> str:
        return f"{self.sdk}-{'-'.join(self.apple_archs)}"

class AppleGoBuilder(Builder):
    def __init__(self, build_dir: str):
        super().__init__(build_dir)
        self.framework_dir = os.path.join(self.lib_dir, "apple_xcframework")
        delete_dir_if_exists(self.framework_dir)
        create_dir_if_not_exists(self.framework_dir)
        self.lib_file = "libXray.a"
        self.lib_header_file = "libXray.h"

        self.ios_targets = [
            AppleTarget(
                "ios",
                "arm64",
                "arm64",
                "iphoneos",
                "15.0",
            ),
        ]

        self.ios_simulator_targets = [
            AppleTarget(
                "ios",
                "amd64",
                "x86_64",
                "iphonesimulator",
                "15.0",
            ),
            AppleTarget(
                "ios",
                "arm64",
                "arm64",
                "iphonesimulator",
                "15.0",
            ),
        ]

        # keep same with flutter
        self.macos_targets = [
            AppleTarget(
                "darwin",
                "amd64",
                "x86_64",
                "macosx",
                "10.14",
            ),
            AppleTarget(
                "darwin",
                "arm64",
                "arm64",
                "macosx",
                "10.14",
            ),
        ]

        self.tvos_targets = [
            AppleTarget(
                "ios",
                "arm64",
                "arm64",
                "appletvos",
                "17.0",
            ),
        ]

        self.tv_simulator_targets = [
            AppleTarget(
                "ios",
                "amd64",
                "x86_64",
                "appletvsimulator",
                "17.0",
            ),
            AppleTarget(
                "ios",
                "arm64",
                "arm64",
                "appletvsimulator",
                "17.0",
            ),
        ]

    def before_build(self):
        self.reset_files()
        super().before_build()
        self.clean_lib_dirs(["LibXray.xcframework"])
        self.prepare_static_lib()

    def build(self):
        self.before_build()
        # build ios
        ios_lib = self.build_targets(self.ios_targets)[0]
        self.create_framework(ios_lib)

        ios_simulator_libs = self.build_targets(self.ios_simulator_targets)
        ios_simulator_lib = self.merge_static_lib(ios_simulator_libs)
        self.create_framework(ios_simulator_lib)

        # build macos
        macos_libs = self.build_targets(self.macos_targets)
        macos_lib = self.merge_static_lib(macos_libs)
        self.create_framework(macos_lib)
        # build tvos
        tvos_lib = self.build_targets(self.tvos_targets)[0]
        self.create_framework(tvos_lib)

        tv_simulator_libs = self.build_targets(self.tv_simulator_targets)
        tv_simulator_lib = self.merge_static_lib(tv_simulator_libs)
        self.create_framework(tv_simulator_lib)

        self.after_build()

        self.create_xcframework([ios_lib, ios_simulator_lib, macos_lib, tvos_lib, tv_simulator_lib])

    def build_targets(self, targets: list[AppleTarget]) -> list[AppleStaticLib]:
        libs = []
        for target in targets:
            self.run_build_cmd(
                target.platform,
                target.go_arch,
                target.apple_arch,
                target.sdk,
                target.min_version,
            )
            libs.append(AppleStaticLib(target.sdk, [target.apple_arch]))

        return libs

    def run_build_cmd(
        self, platform: str, go_arch: str, apple_arch: str, sdk: str, min_version: str
    ):
        output_dir = os.path.join(self.framework_dir, f"{sdk}-{apple_arch}")
        create_dir_if_not_exists(output_dir)
        output_file = os.path.join(output_dir, self.lib_file)
        sdk_path = self.get_sdk_dir_path(sdk)
        min_version_flag = f"-m{sdk}-version-min={min_version}"
        flags = f"-isysroot {sdk_path} {min_version_flag} -arch {apple_arch}"
        run_env = os.environ.copy()
        run_env["GOOS"] = platform
        run_env["GOARCH"] = go_arch
        run_env["GOFLAGS"] = f"-tags={platform}"
        run_env["CC"] = f"xcrun --sdk {sdk} --toolchain {sdk} clang"
        run_env["CXX"] = f"xcrun --sdk {sdk} --toolchain {sdk} clang++"
        run_env["CGO_CFLAGS"] = flags
        run_env["CGO_CXXFLAGS"] = flags
        run_env["CGO_LDFLAGS"] = f"{flags} -Wl,-Bsymbolic-functions"
        run_env["CGO_ENABLED"] = "1"
        run_env["DARWIN_SDK"] = sdk

        cmd = [
            "go",
            "build",
            "-ldflags=-w",
            f"-o={output_file}",
            "-buildmode=c-archive",
        ]
        os.chdir(self.lib_dir)
        print(run_env)
        print(cmd)
        ret = subprocess.run(cmd, env=run_env)
        if ret.returncode != 0:
            raise Exception(f"run_build_cmd for {platform} {apple_arch} {sdk} failed")

    def get_sdk_dir_path(self, sdk: str) -> str:
        cmd = [
            "xcrun",
            "--sdk",
            sdk,
            "--show-sdk-path",
        ]
        print(cmd)
        ret = subprocess.run(cmd, capture_output=True)
        if ret.returncode != 0:
            raise Exception(f"get_sdk_dir_path for {sdk} failed")
        return ret.stdout.decode().replace("\n", "")

    def merge_static_lib(self, libs: list[AppleStaticLib]) -> AppleStaticLib:
        cmd = [
            "lipo",
            "-create",
        ]
        sdk = libs[0].sdk
        arches = list(set([item for row in map(lambda x: x.apple_archs, libs) for item in row]))
        arches.sort()
        for arch in arches:
            lib_dir = os.path.join(self.framework_dir, f"{sdk}-{arch}")
            lib_file = os.path.join(lib_dir, self.lib_file)
            cmd.extend(["-arch", arch, lib_file])
        arch = "-".join(arches)
        output_dir = os.path.join(self.framework_dir, f"{sdk}-{arch}")
        create_dir_if_not_exists(output_dir)
        output_file = os.path.join(output_dir, self.lib_file)
        cmd.extend(["-output", output_file])
        print(cmd)
        ret = subprocess.run(cmd)
        if ret.returncode != 0:
            raise Exception(f"merge_static_lib for {sdk} failed")
        return AppleStaticLib(sdk, arches)

    def create_framework(self, lib: AppleStaticLib):
        lib_name = lib.lib_name()

        framework_dir = os.path.join(self.framework_dir, lib_name, "LibXray.framework")
        create_dir_if_not_exists(framework_dir)

        info_plist = os.path.join(self.build_dir, "template", "AppleGoInfo.plist")
        shutil.copy(info_plist, framework_dir)

        include_dir = os.path.join(framework_dir, "Headers")
        create_dir_if_not_exists(include_dir)

        header_file = os.path.join(
            self.framework_dir,
            f"{lib.sdk}-{lib.apple_archs[0]}",
            self.lib_header_file
        )
        shutil.copy(header_file, include_dir)

        lib_file = os.path.join(
            self.framework_dir,
            lib_name,
            self.lib_file
        )
        lib_dst = os.path.join(
            framework_dir,
            "LibXray"
        )
        shutil.copy(lib_file, lib_dst)


    def create_xcframework(self, libs: list[AppleStaticLib]):
        frameworks = map(lambda x: os.path.join(self.framework_dir, x.lib_name(), "LibXray.framework"), libs)
        cmd = ["xcodebuild", "-create-xcframework"]
        for framework in frameworks:
            cmd.extend(["-framework", framework])

        output_file = os.path.join(self.lib_dir, "LibXray.xcframework")
        cmd.extend(["-output", output_file])

        print(cmd)
        ret = subprocess.run(cmd)
        if ret.returncode != 0:
            raise Exception(f"create_framework failed")

    def after_build(self):
        super().after_build()
        self.reset_files()
