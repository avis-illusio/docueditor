#!/bin/sh
# PyInstaller bundles libstdc++ from the build image.  System fcitx5/ibus Qt
# plugins may need a newer CXXABI, so prefer the system libstdc++ when it
# provides CXXABI_1.3.15.
for lib in /usr/lib/libstdc++.so.6 /usr/lib64/libstdc++.so.6 \
           /usr/lib/x86_64-linux-gnu/libstdc++.so.6 \
           /usr/lib/aarch64-linux-gnu/libstdc++.so.6; do
    if [ -r "$lib" ] && grep -aq 'CXXABI_1.3.15' "$lib"; then
        LD_PRELOAD="$lib${LD_PRELOAD:+:$LD_PRELOAD}"
        export LD_PRELOAD
        break
    fi
done
exec /opt/docueditor/docueditor "$@"
