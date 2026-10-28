#pragma once

#include <experiment.hpp>
#include <rclcpp/rclcpp.hpp>
#include <thread>

namespace experiment {
struct Sent {
    std::uint64_t sequence;
    std::uint64_t prepare_ns;
    std::uint64_t begin_ns;
    std::uint64_t end_ns;
};
struct Received {
    std::uint64_t sequence;
    std::uint64_t arrival_ns;
    bool valid;
};
struct Tick {
    std::uint64_t sequence;
    std::uint64_t planned_ns;
    std::uint64_t woke_ns;
    std::uint64_t skipped_after;
};

inline rclcpp::QoS qos(const Options& options) {
    auto result = rclcpp::QoS(rclcpp::KeepLast(options.slots));
    if (options.profile != "default") {
        result.best_effort();
    }
    return result;
}

inline bool mark(const std::filesystem::path& path) {
    std::ofstream file(path);
    file << "ready\n";
    file.close();
    return !file.fail();
}

template<class Message>
int subscriber(const Options& options) {
    const auto start = now_ns();
    const auto before = resources();
    auto node_options = rclcpp::NodeOptions().use_intra_process_comms(false);
    auto node = std::make_shared<rclcpp::Node>("benchmark_subscriber", node_options);
    rclcpp::executors::SingleThreadedExecutor executor;
    executor.add_node(node);
    const auto total = options.samples + options.warmup;
    std::vector<Received> received;
    received.reserve(static_cast<std::size_t>(total * 2));
    std::uint64_t excess_callbacks = 0;
    auto subscription = node->create_subscription<Message>(options.topic, qos(options),
        [&](typename Message::SharedPtr message) {
            // The endpoint is entry to the ordinary typed ROS callback. This
            // shared_ptr owns a process-local message; no shared-memory view
            // escapes. UniquePtr dispatch would add another full rclcpp copy.
            const auto arrival = now_ns();
            bool valid = message->payload.size() == options.bytes;
            if (valid) {
                valid = message->payload.front() == first_marker && message->payload.back() == last_marker;
            }
            if (received.size() < received.capacity()) {
                received.push_back({message->sequence, arrival, valid});
            } else {
                ++excess_callbacks;
            }
            if (received.size() >= total) {
                executor.cancel();
            }
        });
    // Match both endpoints before the controller starts sample 1. Seeing the
    // reader at the writer alone does not establish reciprocal DDS discovery.
    const auto discovery_end = Clock::now() + discovery_timeout;
    while (rclcpp::ok() && subscription->get_publisher_count() == 0 && Clock::now() < discovery_end) {
        std::this_thread::sleep_for(control_poll);
    }
    if (!rclcpp::ok() || subscription->get_publisher_count() == 0 ||
        !mark(options.directory / "subscriber_ready")) {
        return 1;
    }
    executor.spin();
    const auto end = now_ns();
    const auto after = resources();
    std::ofstream data(options.directory / "received.csv");
    data << "sequence,arrival_ns,valid\n";
    for (const auto& sample : received) {
        data << sample.sequence << ',' << sample.arrival_ns << ',' << sample.valid << '\n';
    }
    data.close();
    std::ofstream stats(options.directory / "subscriber.csv");
    stats << "excess_callbacks\n" << excess_callbacks << '\n';
    stats.close();
    const bool saved = save_resources(options.directory / "subscriber_resources.csv", before, after, start, end);
    if (data.fail() || stats.fail() || !saved || !mark(options.directory / "subscriber_done")) {
        return 1;
    }
    return 0;
}

template<class Message>
int publisher(const Options& options) {
    const auto start = now_ns();
    const auto before = resources();
    auto node_options = rclcpp::NodeOptions().use_intra_process_comms(false);
    auto node = std::make_shared<rclcpp::Node>("benchmark_publisher", node_options);
    auto publisher = node->create_publisher<Message>(options.topic, qos(options));
    auto message = std::make_unique<Message>();
    message->payload.resize(options.bytes);
    message->payload.front() = first_marker;
    message->payload.back() = last_marker;
    const auto total = options.samples + options.warmup;
    std::vector<Sent> sent;
    std::vector<Tick> ticks;
    sent.reserve(static_cast<std::size_t>(total));
    ticks.reserve(static_cast<std::size_t>(total));
    std::ofstream capabilities(options.directory / "capabilities.txt");
    capabilities << "publisher_can_loan_messages=" << publisher->can_loan_messages() << '\n';
    capabilities << "application_publish=copy\napplication_receive=shared_ptr_local_copy\n";
    capabilities.close();

    const auto discovery_end = Clock::now() + discovery_timeout;
    while (rclcpp::ok() && publisher->get_subscription_count() == 0 && Clock::now() < discovery_end) {
        std::this_thread::sleep_for(control_poll);
    }
    if (!rclcpp::ok() || publisher->get_subscription_count() == 0) {
        std::cerr << "Subscriber discovery deadline exceeded\n";
        return 1;
    }
    if (!mark(options.directory / "publisher_ready")) {
        return 1;
    }
    const auto go_end = Clock::now() + discovery_timeout;
    while (rclcpp::ok() && !std::filesystem::exists(options.directory / "go") && Clock::now() < go_end) {
        std::this_thread::sleep_for(control_poll);
    }
    if (!rclcpp::ok() || !std::filesystem::exists(options.directory / "go")) {
        return 1;
    }

    const auto period = std::chrono::nanoseconds(options.period_ns);
    auto next = Clock::now();
    Resources formal_before;
    std::uint64_t formal_start = 0;
    for (std::uint64_t sequence = 1; sequence <= total; ++sequence) {
        if (!rclcpp::ok()) {
            return 1;
        }
        if (sequence == options.warmup + 1) {
            std::this_thread::sleep_for(warmup_drain);
            formal_before = resources();
            formal_start = now_ns();
            next = Clock::now();
        }
        const auto planned = next;
        std::this_thread::sleep_until(planned);
        const auto woke = Clock::now();
        const auto prepare = now_ns();
        message->sequence = sequence;
        const auto begin = now_ns();
        publisher->publish(*message);
        const auto end = now_ns();
        sent.push_back({sequence, begin - prepare, begin, end});
        next = planned + period;
        const auto completed = Clock::now();
        std::uint64_t skipped = 0;
        if (next <= completed) {
            skipped = static_cast<std::uint64_t>((completed - next) / period) + 1;
            next += period * skipped;
        }
        ticks.push_back({sequence, pacing_ns(planned), pacing_ns(woke), skipped});
    }
    const auto formal_end = now_ns();
    const auto formal_after = resources();
    const bool formal_saved = save_resources(options.directory / "publisher_formal_resources.csv",
        formal_before, formal_after, formal_start, formal_end);

    std::ofstream data(options.directory / "sent.csv");
    data << "sequence,prepare_ns,begin_ns,end_ns\n";
    for (const auto& sample : sent) {
        data << sample.sequence << ',' << sample.prepare_ns << ',' << sample.begin_ns << ',' << sample.end_ns << '\n';
    }
    data.close();
    std::ofstream timing(options.directory / "timing.csv");
    timing << "sequence,planned_ns,woke_ns,skipped_after\n";
    for (const auto& tick : ticks) {
        timing << tick.sequence << ',' << tick.planned_ns << ',' << tick.woke_ns << ',' << tick.skipped_after << '\n';
    }
    timing.close();
    std::ofstream stats(options.directory / "publisher.csv");
    stats << "slots,published\n" << options.slots << ',' << sent.size() << '\n';
    stats.close();
    const bool saved = save_resources(options.directory / "publisher_resources.csv", before, resources(), start, now_ns());
    if (!formal_saved || !saved || data.fail() || timing.fail() || stats.fail() ||
        !mark(options.directory / "publisher_done")) {
        return 1;
    }

    // Retain the writer until the controller has drained the reader, matching
    // the native Vinc workload's lifetime instead of losing asynchronous tails.
    const auto finish_end = Clock::now() + post_publish_timeout;
    while (rclcpp::ok() && !std::filesystem::exists(options.directory / "finish") && Clock::now() < finish_end) {
        std::this_thread::sleep_for(control_poll);
    }
    return std::filesystem::exists(options.directory / "finish") ? 0 : 1;
}

template<class Message>
int workload(const Options& options) {
    if (options.role == "publisher") {
        return publisher<Message>(options);
    }
    return subscriber<Message>(options);
}
}
