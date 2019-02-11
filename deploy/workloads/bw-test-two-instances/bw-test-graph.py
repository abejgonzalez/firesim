import matplotlib
# don't use xwindow
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
import re
import sys

DATA_RE = re.compile(r".*packet timestamp: (\d+), len: (\d+)")
TIME_STEP = 100000
CYCLES_PER_NANO = 3.2
CYCLES_PER_MILLI = CYCLES_PER_NANO * 1e6
BITS_PER_WORD = 256 # also the flit size 
TEST_PERIOD = 100 * 1000 * 1000
START_CYCLE = TEST_PERIOD
END_CYCLE = 9 * TEST_PERIOD

def parse_log(f):
    data = []
    for line in f:
        match = DATA_RE.match(line)
        if match:
            tss, lens = match.groups()
            yield (int(tss), int(lens))

def compute_bw(packet_data):
    window_end = 0
    cycles = []
    totals = []
    cur_total = 0
    #for (ts, plen) in packet_data:
    #    print("ts " + str(ts) + "ps:" + str(plen))

    for (ts, plen) in packet_data:
        if ts >= END_CYCLE:
            #print("reached endcycle" + str(END_CYCLE) + " " + str(ts))
            break
        if ts >= window_end:
            while window_end < ts:
                cycles.append(window_end)
                totals.append(cur_total)
                #print("(" + str(window_end) + "," + str(cur_total) + ")")
                window_end += TIME_STEP
                cur_total = 0
        else:
            cur_total += plen
            #print("after end (" + str(window_end) + "," + str(cur_total) + ")")
            #print("ts " + str(ts))
    cycles.append(window_end)
    totals.append(cur_total)

    #for (m, b) in zip(cycles, totals):
    #    print("(" + str(m) + "," + str(b) + ")")
    #print("done")

    millis = [(cycles / CYCLES_PER_MILLI) for cycles in cycles]
    bandwidths = [((total * BITS_PER_WORD) / (TIME_STEP / CYCLES_PER_NANO)) for total in totals]
    
    #for (m, b) in zip(millis, bandwidths):
    #    print("(" + str(m) + "," + str(b) + ")")

    return millis, bandwidths

def main():
    print("Usage: " + sys.argv[0] + " LOG_AND_OUTPUT_DIR")

    #colors = ['orange', 'purple', 'blue', 'green']
    #colors = ['0.1', '0.3', '0.5', '0.7', '0.9']
    colors = ['0.3']
    series = []

    basedir = sys.argv[1]

    inputlogs = [
        #basedir + "/1/switch0/switchlog",
        basedir + "/10/switch0/switchlog",
        #basedir + "/40/switch0/switchlog",
        #basedir + "/100/switch0/switchlog",
        #basedir + "/200/switch0/switchlog",
    ]

    print("using:")
    print(inputlogs)

    outputfile = basedir + "/bw-test-graph.pdf"
    maxbw = []

    for (fname, color) in zip(inputlogs, colors):
        with open(fname) as f:
            data = parse_log(f)
            [times, bandwidths] = compute_bw(data)
            maxbw.append(max(bandwidths))
            #print(max(bandwidths))
            ser, = plt.plot(times, bandwidths, color=color)
            series.append(ser)

    for i in range(1, 8):
        cycle = i * TEST_PERIOD + START_CYCLE
        millis = cycle / CYCLES_PER_MILLI
        plt.axvline(x=millis, color='gray', linewidth=1, linestyle=':')

    fig = plt.gcf()
    fig.set_size_inches(6, 3.75)
    ax = fig.add_subplot(111)
    ax.text(210, 15, '1 Gb/s', size='10')
    ax.text(172, 80, '10 Gb/s',  size='10')
    ax.text(108, 145, '40 Gb/s', size='10')
    ax.text(40, 185, '100 Gb/s', size='10')
    ax.text(40, 285, '200 Gb/s', size='10')

    start_time = START_CYCLE / CYCLES_PER_MILLI
    end_time = END_CYCLE / CYCLES_PER_MILLI

    #plt.legend(series, ['1 Gb/s', '10 Gb/s', '40 Gb/s', '100 Gb/s'])
    plt.xlabel("Time (ms)", size='10')
    plt.ylabel("Bandwidth (Gb/s)", size='10')
    plt.axis([start_time, end_time, 0, max(maxbw) + 10])
    plt.savefig(outputfile)
    plt.show()

if __name__ == "__main__":
    main()
