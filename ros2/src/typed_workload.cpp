#include BENCH_MESSAGE_HEADER
#include <workload.hpp>

namespace experiment {
int BENCH_FUNCTION(const Options& options) {
    return workload<BENCH_MESSAGE_TYPE>(options);
}
}
