# Third-party sources / 第三方來源

`library/open-vinc` is an unmodified Git submodule at the revision in
`cmake/open-vinc-revision.txt`. Its nested submodules, incorporated-code notices,
licenses and redistribution inventory remain owned by that project. See its
`THIRD_PARTY_NOTICES.txt`, `LICENSE`, `NOTICE`, and `library/README.md`.
Open-VINC's CMake deployment copies those notices beside the native binaries.
Dependencies are not all necessarily linked into every executable.

`native/driver.cpp`, `native/module.cpp` and `native/include/benchmark.hpp` derive
from that pinned project's Message Bus benchmark, under Apache-2.0. Their changes
are identified in file headers and our NOTICE. The remaining new suite code is
also Apache-2.0. Preserve this suite's LICENSE/NOTICE when distributing it or its
modified benchmark artifacts.

No Apex.AI `performance_test` code is copied or linked. Its testing methodology
is referenced; this suite does not claim upstream endorsement or compatibility
with its CSV format. A future adapter must separately preserve any incorporated
upstream code's attribution and document its version.

框架與其第三方相依保持原樣，授權清單由固定版本的上游維護；發佈本測試產物時，
同時附上本專案及框架部署的授權／署名檔案。不同 binary 的實際相依範圍可能不同。

The optional `ros2/` workload is original Apache-2.0 suite code. It dynamically
uses system-installed ROS 2 Jazzy/rclcpp, rmw_fastrtps_cpp, Fast DDS and Fast CDR;
their source is not vendored here. Package versions and binary hashes accompany
measurements. Their upstream license/notice files remain with the installed
packages. Redistribution of a ROS runtime must include its applicable dependency
licenses/notices as well; this suite's LICENSE does not replace them.
