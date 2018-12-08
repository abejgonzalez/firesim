#ifndef FLIT_H
#define FLIT_H

#include <stdlib.h>

#define BROADCAST_ADJUSTED (0xffff)

/* ----------------------------------------------------
 * buffer flit operations
 * ----------------------------------------------------
 */ 

class NetworkFlit {
    public:
        NetworkFlit();
        ~NetworkFlit();
        uint8_t* data_buffer;
        bool last;
};

NetworkFlit::NetworkFlit()
    : last(false) {
    this->data_buffer = (uint8_t*) malloc(FLIT_SIZE_BYTES);
}

NetworkFlit::~NetworkFlit() {
    free(this->data_buffer);
}

/**
 * get a flit from recv_buf, given the token id
 *
 * @input recv_buf buffer to read from
 * @input tokenid id to index into the recv_buf
 * @output ptr within recv_buf where the FLIT_SIZE_BYTES amt of data is held
 */
uint8_t* get_flit(uint8_t * recv_buf, int tokenid) {
    int base = tokenid / TOKENS_PER_BIGTOKEN;
    int offset = tokenid % TOKENS_PER_BIGTOKEN;
    return (recv_buf + (base * BIGTOKEN_SIZE_BYTES) + (FLIT_SIZE_BYTES * (offset + 1)));
}

/**
 * write a flit to send_buf
 *
 * @input send_buf buffer to write flit data to
 * @input tokenid id to index into the send_buf
 * @input flit_buf buffer data to move to the send_buf
 */
void write_flit(uint8_t * send_buf, int tokenid, uint8_t * flit_buf) {
    int base = tokenid / TOKENS_PER_BIGTOKEN;
    int offset = tokenid % TOKENS_PER_BIGTOKEN;
    memcpy( send_buf + (base * BIGTOKEN_SIZE_BYTES) + (FLIT_SIZE_BYTES * (offset + 1)), flit_buf, FLIT_SIZE_BYTES );
}

/**
 * write a valid to the flit
 *
 * @input send_buf buffer to write the valid bit to
 * @input tokenid id to index into the send_buf
 */
void write_valid_flit(uint8_t * send_buf, int tokenid) {
    int base = tokenid / TOKENS_PER_BIGTOKEN;
    int offset = tokenid % TOKENS_PER_BIGTOKEN;

    uint8_t* lrv = send_buf + (base * BIGTOKEN_SIZE_BYTES);

    printf("wvf: flit: item3(0x%x) item2(0x%x) item1(0x%x) item0(0x%x)\n",
            *((uint64_t*)(lrv + (3 * FLIT_SIZE_BYTES))),
            *((uint64_t*)(lrv + (2 * FLIT_SIZE_BYTES))),
            *((uint64_t*)(lrv + (1 * FLIT_SIZE_BYTES))),
            *((uint64_t*)(lrv + (0 * FLIT_SIZE_BYTES))));

    //int bitoffset = 43 + (offset * 3);
    int bitoffset = (FLIT_SIZE_BITS - (TOKENS_PER_BIGTOKEN * 3)) + (offset * 3);
    *(lrv + (bitoffset / 8)) |= (1 << (bitoffset % 8));
}

/**
 * write the last field in the flit
 *
 * @input send_buf buffer to write the last bit to
 * @input tokenid id to index into the send_buf
 * @input is_last bool to write into the last bit spot
 */
int write_last_flit(uint8_t * send_buf, int tokenid, bool is_last) {
    int base = tokenid / TOKENS_PER_BIGTOKEN;
    int offset = tokenid % TOKENS_PER_BIGTOKEN;

    uint8_t* lrv = send_buf + (base * BIGTOKEN_SIZE_BYTES);

    printf("wlf: flit: item3(0x%x) item2(0x%x) item1(0x%x) item0(0x%x)\n",
            *((uint64_t*)(lrv + (3 * FLIT_SIZE_BYTES))),
            *((uint64_t*)(lrv + (2 * FLIT_SIZE_BYTES))),
            *((uint64_t*)(lrv + (1 * FLIT_SIZE_BYTES))),
            *((uint64_t*)(lrv + (0 * FLIT_SIZE_BYTES))));

    //uint64_t * lrv = ((uint64_t*)send_buf) + base*8;
    //int bitoffset = 45 + (offset * 3);
    int bitoffset = (FLIT_SIZE_BITS - (TOKENS_PER_BIGTOKEN * 3)) + 2 + (offset * 3);
    *(lrv + (bitoffset / 8)) |= (is_last << (bitoffset % 8));
    //*lrv |= (((uint64_t)is_last) << bitoffset);
}

/**
 * for a particular tokenid, determine if the flit is valid
 *
 * @input recv_buf buffer to read from
 * @input tokenid id to index into the recv_buf
 * @output bool indicating whether the flit is valid or not
 */
bool is_valid_flit(uint8_t * recv_buf, int tokenid) {
    int base = tokenid / TOKENS_PER_BIGTOKEN;
    int offset = tokenid % TOKENS_PER_BIGTOKEN;

    uint8_t* lrv = recv_buf + (base * BIGTOKEN_SIZE_BYTES);

    printf("ivf: flit: item3(0x%x) item2(0x%x) item1(0x%x) item0(0x%x)\n",
            *((uint64_t*)(lrv + (3 * FLIT_SIZE_BYTES))),
            *((uint64_t*)(lrv + (2 * FLIT_SIZE_BYTES))),
            *((uint64_t*)(lrv + (1 * FLIT_SIZE_BYTES))),
            *((uint64_t*)(lrv + (0 * FLIT_SIZE_BYTES))));

    //int bitoffset = 43 + (offset * 3);
    int bitoffset = (FLIT_SIZE_BITS - (TOKENS_PER_BIGTOKEN * 3)) + (offset * 3);

    return *(lrv + (bitoffset / 8)) >> (bitoffset % 8);
}

/**
 * for a particular tokenid, determine if the flit is the last
 *
 * @input recv_buf buffer to read from
 * @input tokenid id to index into the recv_buf
 * @output bool indicating whether the flit is valid or not
 */
bool is_last_flit(uint8_t * recv_buf, int tokenid) {
    int base = tokenid / TOKENS_PER_BIGTOKEN;
    int offset = tokenid % TOKENS_PER_BIGTOKEN;

    uint8_t* lrv = recv_buf + (base * BIGTOKEN_SIZE_BYTES);

    printf("ilf: flit: item3(0x%x) item2(0x%x) item1(0x%x) item0(0x%x)\n",
            *((uint64_t*)(lrv + (3 * FLIT_SIZE_BYTES))),
            *((uint64_t*)(lrv + (2 * FLIT_SIZE_BYTES))),
            *((uint64_t*)(lrv + (1 * FLIT_SIZE_BYTES))),
            *((uint64_t*)(lrv + (0 * FLIT_SIZE_BYTES))));

    //int bitoffset = 45 + (offset * 3);
    int bitoffset = (FLIT_SIZE_BITS - (TOKENS_PER_BIGTOKEN * 3)) + 2 + (offset * 3);
    return *(lrv + (bitoffset / 8)) >> (bitoffset % 8);
}

/**
 * get dest mac from flit, then get port from mac
 *
 * @input flit_buf buffer data to get the port
 * @input current_port current port
 * @output uint16_t representing the port from the mac address
 */
uint16_t get_port_from_flit(uint8_t* flit_buf, int current_port) {

    printf("gpff: flit: item3(0x%x) item2(0x%x) item1(0x%x) item0(0x%x)\n",
            *((uint64_t*)(flit_buf + (3 * FLIT_SIZE_BYTES))),
            *((uint64_t*)(flit_buf + (2 * FLIT_SIZE_BYTES))),
            *((uint64_t*)(flit_buf + (1 * FLIT_SIZE_BYTES))),
            *((uint64_t*)(flit_buf + (0 * FLIT_SIZE_BYTES))));

    // AJG: TODO: Check where in the flit the dest mac is
    uint16_t is_multicast = (*((uint64_t*)flit_buf) >> 16) & 0x1;
    uint16_t flit_low = (*((uint64_t*)flit_buf) >> 48) & 0xFFFF; // indicates dest
    uint16_t sendport = (__builtin_bswap16(flit_low));

    if (is_multicast)
        return BROADCAST_ADJUSTED;

    sendport = sendport & 0xFFFF;
    printf("mac: %04x\n", sendport);

    // At this point, we know the MAC address is not a broadcast address,
    // so we can just look up the port in the mac2port table
    sendport = mac2port[sendport];

    if (sendport == NUMDOWNLINKS) {
        // this has been mapped to "any uplink", so pick one
        int randval = rand() % NUMUPLINKS;
        sendport = randval + NUMDOWNLINKS;
        printf("sending to random uplink.\n");
        printf("port: %04x\n", sendport);
    }
    printf("port: %04x\n", sendport);
    return sendport;
}

#endif
