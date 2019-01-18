#include <functional>
#include <queue>
#include <algorithm>
#include <stdio.h>
#include <string.h>
#include <stdint.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <sys/fcntl.h>
#include <unistd.h>
#include <omp.h>
#include <cstdlib>

//#define IGNORE_PRINTF

#ifdef IGNORE_PRINTF
#define printf(fmt, ...) (0)
#endif

// param: link latency in cycles
// assuming 3.2 GHz, this number / 3.2 = link latency in ns
// e.g. setting this to 35000 gives you 35000/3.2 = 10937.5 ns latency
// IMPORTANT: this must be a multiple of 7
//
// THIS IS SET BY A COMMAND LINE ARGUMENT. DO NOT CHANGE IT HERE.
//#define LINKLATENCY 6405
int LINKLATENCY = 0;

// param: switching latency in cycles
// assuming 3.2 GHz, this number / 3.2 = switching latency in ns
//
// THIS IS SET BY A COMMAND LINE ARGUMENT. DO NOT CHANGE IT HERE.
int switchlat = 0;

#define SWITCHLATENCY (switchlat)

// param: numerator and denominator of bandwidth throttle
// Used to throttle outbound bandwidth from port
//
// THESE ARE SET BY A COMMAND LINE ARGUMENT. DO NOT CHANGE IT HERE.
int throttle_numer = 1;
int throttle_denom = 1;

// uncomment to use a limited output buffer size, OUTPUT_BUF_SIZE
//#define LIMITED_BUFSIZE

// size of output buffers, in # of flits
// only if LIMITED BUFSIZE is set
// TODO: expose in manager
// AJG: TODO: According to Sagar this doesn't have to change
#define OUTPUT_BUF_SIZE (131072L)

// pull in # clients config
#define NUMCLIENTSCONFIG
#include "switchconfig.h"
#undef NUMCLIENTSCONFIG

// DO NOT TOUCH
//#define MAX_BW (800)
//#define FLIT_SIZE_BITS (256)
#define MAX_BW (200)
#define FLIT_SIZE_BITS (64)
#define BIGTOKEN_SIZE_BITS (512)
#define NUM_TOKENS (LINKLATENCY)

#define FLIT_SIZE_BYTES (FLIT_SIZE_BITS / 8)
#define BIGTOKEN_SIZE_BYTES (BIGTOKEN_SIZE_BITS / 8)

#define TOKENS_PER_BIGTOKEN ((uint16_t)((BIGTOKEN_SIZE_BYTES*8)/(FLIT_SIZE_BITS+3)))
#define NUM_BIGTOKENS (NUM_TOKENS/TOKENS_PER_BIGTOKEN)
#define BUFSIZE_BYTES (NUM_BIGTOKENS*BIGTOKEN_SIZE_BYTES)

// DO NOT TOUCH
#define SWITCHLAT_NUM_TOKENS (SWITCHLATENCY)
#define SWITCHLAT_NUM_BIGTOKENS (SWITCHLAT_NUM_TOKENS/TOKENS_PER_BIGTOKEN)
#define SWITCHLAT_BUFSIZE_BYTES (SWITCHLAT_NUM_BIGTOKENS*BIGTOKEN_SIZE_BYTES)

uint64_t this_iter_cycles_start = 0;

// pull in mac2port array
#define MACPORTSCONFIG
#include "switchconfig.h"
#undef MACPORTSCONFIG

#include "flit.h"
#include "baseport.h"
#include "shmemport.h"
#include "socketport.h"
#include "sshport.h"

// TODO: replace these port mapping hacks with a mac -> port mapping,
// could be hardcoded

BasePort * ports[NUMPORTS];

/* switch from input ports to output ports */
void do_fast_switching() {
#pragma omp parallel for
    for (int port = 0; port < NUMPORTS; port++) {
        ports[port]->setup_send_buf();
    }


// preprocess from raw input port to packets
#pragma omp parallel for
for (int port = 0; port < NUMPORTS; port++) {
    BasePort * current_port = ports[port];
    uint8_t * input_port_buf = current_port->current_input_buf;

    for (int tokenno = 0; tokenno < NUM_TOKENS; tokenno++) {
        if (is_valid_flit(input_port_buf, tokenno)) {
            uint8_t* flit = get_flit(input_port_buf, tokenno);
            
            printf("switch: port(%d) inbuf_ptr(%p) postprocess flit: (", port, input_port_buf);
            printArray(flit, FLIT_SIZE_BYTES);
            printf(")\n");

            switchpacket * sp;
            if (!(current_port->input_in_progress)) {
                printf("switch: current_port(%d)->input_in_progress is setup as current flit\n", port);
                sp = (switchpacket*)calloc(sizeof(switchpacket), 1);
                sp->dat = (uint8_t*)calloc(FLIT_SIZE_BYTES, ETH_MAX_WORDS + ETH_EXTRA_FLITS);
                current_port->input_in_progress = sp;

                // here is where we inject switching latency. this is min port-to-port latency
                sp->timestamp = this_iter_cycles_start + tokenno + SWITCHLATENCY;
                sp->sender = port;
            }
            sp = current_port->input_in_progress;

            memcpy( sp->dat + ((sp->amtwritten++) * FLIT_SIZE_BYTES), flit, FLIT_SIZE_BYTES);
            if (is_last_flit(input_port_buf, tokenno)) {
                printf("switch(%d): last flit, push to inputqueue\n", port);
                current_port->inputqueue.push(sp);
                current_port->input_in_progress = NULL;
            }
        }
    }
}

// next do the switching. but this switching is just shuffling pointers,
// so it should be fast. it has to be serial though...

// NO PARALLEL!
// shift pointers to output queues, but in order. basically.
// until the input queues have no more complete packets
// 1) find the next switchpacket with the lowest timestamp across all the inputports
// 2) look at its mac, copy it into the right ports
//          i) if it's a broadcast: sorry, you have to make N-1 copies of it...
//          to put into the other queues

struct tspacket {
    uint64_t timestamp;
    switchpacket * switchpack;

    bool operator<(const tspacket &o) const
    {
        return timestamp > o.timestamp;
    }
};

typedef struct tspacket tspacket;


// TODO thread safe priority queue? could do in parallel?
std::priority_queue<tspacket> pqueue;

for (int i = 0; i < NUMPORTS; i++) {
    while (!(ports[i]->inputqueue.empty())) {
        printf("PORT[%d]: inputqueue to pqueue\n", i);
        switchpacket * sp = ports[i]->inputqueue.front();
        ports[i]->inputqueue.pop();
        pqueue.push( tspacket { sp->timestamp, sp });
    }
}

// next, put back into individual output queues
while (!pqueue.empty()) {
    switchpacket * tsp = pqueue.top().switchpack;
    printf("PORT[None]: pqueue tsp: timestamp(%ld) dat_ptr(%p) amtwritten(%d) amtread(%d) sender(%d)\n", 
           tsp->timestamp,
           tsp->dat,
           tsp->amtwritten,
           tsp->amtread,
           tsp->sender);
    pqueue.pop();
    uint16_t send_to_port = get_port_from_flit(tsp->dat, 0 /* junk remove arg */);
    printf("PORT[None]: packet for port: %x\n", send_to_port);
    printf("PORT[None]: packet timestamp: %ld\n", tsp->timestamp);
    if (send_to_port == BROADCAST_ADJUSTED) {
#define ADDUPLINK (NUMUPLINKS > 0 ? 1 : 0)
        printf("switch: broadcast\n");
        // this will only send broadcasts to the first (zeroeth) uplink.
        // on a switch receiving broadcast packet from an uplink, this should
        // automatically prevent switch from sending the broadcast to any uplink
        for (int i = 0; i < NUMDOWNLINKS + ADDUPLINK; i++) {
            printf("PORT[%d]: numdownlinks(%d), numuplinks(%d), iter(%d)\n", i, NUMDOWNLINKS, ADDUPLINK, i);
            if (i != tsp->sender ) {
                switchpacket * tsp2 = (switchpacket*)malloc(sizeof(switchpacket));
                memcpy(tsp2, tsp, sizeof(switchpacket));
                tsp2->dat = (uint8_t*)malloc(FLIT_SIZE_BYTES*(ETH_MAX_WORDS + ETH_EXTRA_FLITS));
                memcpy(tsp2->dat, tsp->dat, FLIT_SIZE_BYTES*(ETH_MAX_WORDS + ETH_EXTRA_FLITS));
                printf("PORT[%d]: outputqueue tsp2: timestamp(%ld) dat_ptr(%p) amtwritten(%d) amtread(%d) sender(%d)\n", 
                       i,
                       tsp2->timestamp,
                       tsp2->dat,
                       tsp2->amtwritten,
                       tsp2->amtread,
                       tsp2->sender);
                ports[i]->outputqueue.push(tsp2);
            }
        }
        printf("PORT[None]: free pqueue tsp\n");
        free(tsp->dat);
        free(tsp);
    } else {
        printf("PORT[None]: push tsp to PORT[%d]\n", send_to_port);
        ports[send_to_port]->outputqueue.push(tsp);
    }
}


// finally in parallel, flush whatever we can to the output queues based on timestamp

#pragma omp parallel for
for (int port = 0; port < NUMPORTS; port++) {
    BasePort * thisport = ports[port];
    thisport->write_flits_to_output();
}

}

static void simplify_frac(int n, int d, int *nn, int *dd)
{
    int a = n, b = d;

    // compute GCD
    while (b > 0) {
        int t = b;
        b = a % b;
        a = t;
    }

    *nn = n / a;
    *dd = d / a;
}

int main (int argc, char *argv[]) {
    int bandwidth;

    if (argc < 4) {
        // if insufficient args, error out
        fprintf(stdout, "usage: ./switch LINKLATENCY SWITCHLATENCY BANDWIDTH\n");
        fprintf(stdout, "insufficient args provided\n.");
        fprintf(stdout, "LINKLATENCY and SWITCHLATENCY should be provided in cycles.\n");
        fprintf(stdout, "BANDWIDTH should be provided in Gbps\n");
        exit(1);
    }

    LINKLATENCY = atoi(argv[1]);
    switchlat = atoi(argv[2]);
    bandwidth = atoi(argv[3]);

    simplify_frac(bandwidth, MAX_BW, &throttle_numer, &throttle_denom);

    fprintf(stdout, "Using link latency: %d\n", LINKLATENCY);
    fprintf(stdout, "Using switching latency: %d\n", SWITCHLATENCY);
    fprintf(stdout, "BW throttle set to %d/%d\n", throttle_numer, throttle_denom);

    if ((LINKLATENCY % 7) != 0) {
        // if invalid link latency, error out.
        fprintf(stdout, "INVALID LINKLATENCY. Currently must be multiple of 7 cycles.\n");
        exit(1);
    }

    omp_set_num_threads(NUMPORTS); // we parallelize over ports, so max threads = # ports

#define PORTSETUPCONFIG
#include "switchconfig.h"
#undef PORTSETUPCONFIG

    while (true) {

        // handle sends
        //printf("switch: send\n");
#pragma omp parallel for
        for (int port = 0; port < NUMPORTS; port++) {
            ports[port]->send();
        }

        // handle receives. these are blocking per port
        //printf("switch: recv\n");
#pragma omp parallel for
        for (int port = 0; port < NUMPORTS; port++) {
            ports[port]->recv();
        }
 
        //printf("switch: tick_pre\n");
#pragma omp parallel for
        for (int port = 0; port < NUMPORTS; port++) {
            ports[port]->tick_pre();
        }

        //printf("switch: do_fast_switching\n");
        do_fast_switching();

        this_iter_cycles_start += LINKLATENCY; // keep track of time
        //printf("switch: this_iter_cycles_start(%ld)\n", this_iter_cycles_start);

        // some ports need to handle extra stuff after each iteration
        // e.g. shmem ports swapping shared buffers
        //printf("switch: tick\n");
#pragma omp parallel for
        for (int port = 0; port < NUMPORTS; port++) {
            ports[port]->tick();
        }

    }
}
