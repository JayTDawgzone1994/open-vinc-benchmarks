#include <experiment.hpp>
#include <rclcpp/rclcpp.hpp>

int main(int argc, char** argv) {
    experiment::Options options;
    if (!experiment::parse(argc, argv, options)) {
        std::cerr << "usage: ros_benchmark publisher|subscriber default|shm|datasharing bytes slots period_ns samples warmup owned-copy directory topic\n";
        return 2;
    }

    try {
        // ROS only sees its own CLI; benchmark arguments stay in Options.
        int ros_argc = 1;
        rclcpp::init(ros_argc, argv);
        int result = 1;
        if (options.profile != "datasharing") {
            result = experiment::run_frame(options);
        } else {
            switch (options.bytes) {
            case 1024:
                result = experiment::run_frame1k(options);
                break;
            case 1048576:
                result = experiment::run_frame1m(options);
                break;
            case 8388608:
                result = experiment::run_frame8m(options);
                break;
            case 16777216:
                result = experiment::run_frame16m(options);
                break;
            case 33554432:
                result = experiment::run_frame32m(options);
                break;
            case 67108864:
                result = experiment::run_frame64m(options);
                break;
            case 134217728:
                result = experiment::run_frame128m(options);
                break;
            default:
                std::cerr << "No bounded schema for this size\n";
                result = 2;
            }
        }
        rclcpp::shutdown();
        return result;
    } catch (const std::exception& error) {
        // External ROS/DDS and allocator exceptions are a process boundary.
        std::cerr << "ROS benchmark failed: " << error.what() << '\n';
        rclcpp::shutdown();
        return 1;
    }
}
