---
###
# Internet-Draft Markdown Template
#
# Rename this file from draft-todo-yourname-protocol.md to get started.
# Draft name format is "draft-<yourname>-<workgroup>-<name>.md".
#
# For initial setup, you only need to edit the first block of fields.
# Only "title" needs to be changed; delete "abbrev" if your title is short.
# Any other content can be edited, but be careful not to introduce errors.
# Some fields will be set automatically during setup if they are unchanged.
#
# Don't include "-00" or "-latest" in the filename.
# Labels in the form draft-<yourname>-<workgroup>-<name>-latest are used by
# the tools to refer to the current version; see "docname" for example.
#
# This template uses kramdown-rfc: https://github.com/cabo/kramdown-rfc
# You can replace the entire file if you prefer a different format.
# Change the file extension to match the format (.xml for XML, etc...)
#
###
title: "QICK Control and Acquisition Transport Protocol"
abbrev: "QCAT"
category: info

docname: draft-owencochell-art-qcat-latest
submissiontype: independent  # also: "independent", "editorial", "IAB", or "IRTF"
number:
date:
v: 3
area: ART
workgroup: WG Working Group
keyword:
 - next generation
 - unicorn
 - sparkling distributed ledger
venue:
  group: WG
  type: Working Group
  mail: WG@example.com
  arch: https://example.com/WG
  github: USER/REPO
  latest: https://example.com/LATEST

author:
 -
    fullname: Owen Cochell
    organization: University of Illinois Urbana-Champaign
    email: cochell2@illinois.edu

normative:

informative:

...

--- abstract

TODO Abstract


--- middle

# Introduction

This document describes the QICK Control and Acquisition Protocol (QCAT),
an application-level, cross-platform, bi-directional binary protocol for communicating with QICK boards over a network.

TODO

- Add section describing data types
- Need to have a section discussing protocol number
- Add flags section to header?
- Probably need to add CRC
- Discuss importance of working over different physical layers (such as serial)
- Add feature to disable some integrity/delivery checks on reliable lines
- Clarify the terminology behind receiver/transmitter
  - I think just replace with board/client
- Define NULL to be empty data with length 0
- Add section describing what to do on failure
- Use unicode for JSON config string?
- Add figures to control and data read/write showing the payload layout
- Define the array encoding format
- Review some datatypes, can likely choose smaller with no issue
- Many messages are not 32bit aligned
- Add formulas to deduce sub-chunk payload size for each type

## Background

Currently, the QICK ecosystem uses Pyro (CITE) and PyNQ (cite),
which are python only libraries that provide RPC and data transfer mechanisms over a network.
Client's interact with a proxied class that abstracts the firmware
and provides interfaces for setting/querying parameters,
uploading compiled pulse sequences, and reading/writing large segments of data.
All these operations are done via native calls to python class methods,
which are then dispatched to the board.
The results (if any) are then returned to the client in a native python format.
Pickle (CITE) is also used as the primary serialization method,
which is a python only method for serializing python data and classes.

## Motivation

While this workflow is convenient and effective for python environments,
the design makes it difficult for other environments and languages
to interact with QICK environment.
For example, it would not be feasible to develop an alternative client programming environment
in a language other than python, or develop an embedded operating system to manage
the circuit controller in a lower-level C language due to the python centric network stack.
While it is technically possible to interface with the python ecosystem by embedding a python
interpreter or writing a compatibility layer to interface with these components,
it would be prohibitively difficult to develop and maintain projects that use these approaches.

It is for this reason why developing a separate, cross-platform binary protocol is a requirement
to improve interoperability and compatibility with other platforms.
In addition, the current stack adds considerable overhead (TODO: Quantify?) and
the reliance on pickle can lead to serious arbitrary code execution attacks (CITE).

# Conventions and Definitions

{::boilerplate bcp14-tagged}

Hexadecimal (CITE) values are always prefixed with "0x" for clarity.
Each character after the prefix represents a 4bit base-16 value
using standard hexadecimal symbols.

This specification uses a number of terms to refer to various aspects of this protocol,
which will be defined here and used henceforth.

{: vspace="0"}
QICK:
: The Quantum Instrumentation Control Kit (CITE) is an open source qubit
controller consisting of firmware, a quantum pulse programming API, and
notebooks for showcasing pulse programs and compilation.

Binprog:
: A compiled QICK program which is evaluated by the board and converted
into pulse sequences for manipulating the QPU.

Board:
: A device that utilizes QICK firmware to interact with the QPU via pulse operations.
It also exposes various hardware parameters over the network,
and allows for the execution of compiled QICK programs.

Client:
: An end-user device where QICK programs are written via the quantum pulse programming API,
compiled into a QICK binprog, and uploaded to the board via the QCAT protocol.

Chunk:
: A sequence of data representing an operation to be preformed. Chunks encapsulate
a single logical operation.

Packet:
: A complete sequence

# Protocol Overview

~~~ aasvg
{::include art/qcat-packet-layout.ascii-art}
~~~
{: #fig-packet-layout title="QCAT Packet Layout"}

A QCAT packet consists of a few high-level components:\\

{: vspace="0"}
Header:
: Fixed-sized data at the start of a QCAT packet that contains control information about the succeeding chunks.

Chunk:
: A sequence of data representing an operation to be preformed. Chunks encapsulate
a single logical operation.

Chunk Header:
: Fixed-sized data that contains control information on a single chunk.

Chunk Payload:
: The data associated with the chunk, to be used to preform the operation described by the chunk.

This is the format of all QCAT packets, a packet header followed by
a single chunk, which consists of a chunk header and chunk payload.
Each packet MUST define a single top-level chunk; packets with zero
chunks are invalid.
Note, we will cover a special chunk type later which allows
multiple chunks to be present within a single top-level chunk.

## Packet Header

The packet header contains all the necessary information required
to identify QCAT packets, and parse the succeeding chunk.

~~~ protocol
Signature:32,Version:8,Size:32
~~~
{: #fig-header-layout title="Packet Header Layout"}

{: vspace="0"}
Signature: ASCII string of length four
: The ASCII character code for the string "QICK" ("Q"=0x51, "I"=0x49, "C"=0x43, "K"=0x4B)
used for identifying QCAT packets. A parser MUST discard any incoming data
that does not start with this signature.

Version: uint8
: Scalar representing protocol version (TODO: Discuss).

Size: uint32
: Number of bytes in packet after header. A parser MUST read exactly
the number of reported bytes to properly process the packet.

## Chunk Format

### Chunk Header

The chunk header contains all the necessary information required
to identify the chunk and parse it's payload correctly.

~~~ protocol
Chunk Type:16,Sequence Number:32
~~~

{: vspace="0"}
Chunk Type: uint16
: Determines the type of this chunk, which affects how it's payload
is parsed. Discussed later in this specification. If a parser
does not recognize a chunk type, it MAY discard it or respond
with a failure chunk (discussed later).

Sequence Number: uint_32
: Used by the transmitter to relate responses to sent packets.
When the transmitter sends packets, the receiver SHOULD process them in order
and return the results in the order the packets are sent.
While this is the recommendation, we place no hard restrictions on the process order,
which can allow for certain optimizations and lessens the reliance on
fault-tolerant protocols (execution order can be achieved via batch chunks). The only requirement is the receiver MUST
provide this sequence number in it's response so the client
can properly relate the response to the sent message,
and react to failures reported by the receiver (such as an integrity failure).

### Chunk Payload

The chunk payload is an arbitrary sized sequence of data that
contains the data to be consumed by the receiver.
The chunk payload MAY be NULL.
The contents of each chunk type is well defined, and will be discussed
later in this specification.

This size of this payload can be computed via:

Payload Size = Size - 48

# Chunks

QCAT packets can have the following chunks,
which are defined by their type:

- 0x0000: Acknowledgment
- 0x0001: Ping / Pong
- 0x0002: Fetch Config
- 0x0003: Control
- 0x0004: Bulk Data Write
- 0x0005: Bulk Data Read
- 0x0006: Subscribe
- 0x0007: Stream
- 0x0008: Batch

The data encoded by each chunk is contained in the chunk payload.
Be aware, some chunks recursively define a secondary payload within
the chunk payload.
The chunk payload layout and any recursive payloads will
 be described in each chunk section of this specification.

## Acknowledgement

When packets are sent by the transmitter,
the receiver MUST send an acknowledgement chunk in response.
While this mechanism does notify the transmitter
that the receiver has acquired processed their packet
(useful in non-fault tolerant scenarios), it serves another purpose.
The acknowledgement chunk holds the response from the server,
as well as any protocol related error codes.

~~~ protocol
Chunk Header:48,Responding Type:16,Code:8
~~~

{: vspace="0"}
Responding Type: uint16
: The chunk type we are responding to. The receiver MUST set
this field to the chunk type it is responding to.

Code: uint_8
: A code that shows how the server processed the message (see below)

Acknowledgement messages define the following codes:

- 0x00: Success - Receiver processed the chunk and returned a response
- 0x01: Integrity - The chunk did not pass the integrity checks preformed by the receiver, no action taken
- 0x02: Parsing Error - The chunk handler failed to parse the payload, no action taken
- 0x03+: Unknown Error - The receiver is reporting an error we don't know about, no action taken

Any data after these fields will contain the response of the receiver,
hereafter refereed to as the response payload.
The response payload MAY be NULL if the code is Success, and it MUST be NULL
if any other code is used.
The layout of this response payload can vary, and will be described in each chunk section.

## Ping / Pong

This chunk is a harmless NOP used to test connectivity between the transmitter and receiver.
The receiver MUST not preform any action other than responding when received.

~~~ protocol
Chunk Header:48,Ping Data:32
~~~

{: vspace="0"}
Ping Data: ASCII string of length four
: The ASCII character codes for the string "PING" ("P"=0x50, "I"=0x49, "N"=0x4E, "G"=0x47)

### Response

~~~ protocol
Chunk Header:48,ACK Header:24,Pong Data:32
~~~

{: vspace="0"}
Pong Data: ASCII string of length four
: The ASCII character codes for the string "PONG" ("P"=0x50, "O"=0x4f, "N"=0x4E, "G"=0x47)

## Config

This chunk retrieves the dynamic configuration values for a board as a JSON (CITE) ASCII string.
Because board configuration is not formally defined,
we use JSON as a way to dynamically encode the board values.
The payload of the config chunk MUST be NULL.

### Response

The response payload is simply the JSON ASCII string
that can be parsed and loaded via any JSON library.
Again, this data is dynamic, so we put no restrictions
on the fields or datatypes here.

## Control

Control chunks are pre-defined operations that alter the state of the board.
These chunks also define an arbitrary sized control payload,
which contains any parameters used by the control operation.
This payload succeeds the control type parameter, and MAY be NULL.
Control payloads are encoded as protobufs; the scheme is discussed
later in this specification.
These operations SHOULD be small, fast, and have their chunk/response payloads
be under a kilobyte.
You can think of these as the "RPC" operations of this protocol.

TODO: Show figure that defines the different payloads

~~~ protocol
Chunk Header:48,Control Type:16
~~~

{: vspace="0"}
Control Type: uint16
: The type of control message, which determines the layouts
of the control and response payloads. See later in this specification
for a list of control chunk types.

The control payload immediately follows these parameters.

### Response

The response payload has no special layout,
and is instead defined by each control chunk type.
As with the control payload,
the response payloads are encoded as protobufs.
Depending on the chunk type, the response payload MAY be NULL.

## Data Write

Data write chunks are pre-defined operations that transfer a large amount of binary data
with a set of parameters to the receiver. These are similar to control chunks, with the addition that
a large sequence of binary data is also associated with the chunk.

TODO: Show figure that defines the different payloads.
"Parameters" are for the write operation, "write payload"
is the data to write.

~~~ protocol
Chunk Header:48,Write Type:16
~~~

{: vspace="0"}
Write Type: uint16
: The type of write message, which determines the layouts
of the write parameters and write payload. See later in this specification
for a list of write chunk types.

The parameters and write payload immediately follows the write type.
The write payload follows the array encoding format.

### Response

~~~ protocol
Chunk Header:48,ACK Header:24,Code:8
~~~

{: vspace="0"}
Code: uint8
: A code that shows how the receiver processed the message

The following codes are defined:

- 0x00: Success - The receiver successfully wrote the provided data
- 0x01+: Undefined - Unknown code defined by each write type, no action taken

## Data Read

Data read chunks are pre-defined operations that transfer a large amount of binary data
with a set of parameters to the transmitter. These are similar to control chunks, with the addition that
a large sequence of binary data is also associated with the chunk response.

TODO: Show layout of extra parameters

~~~ protocol
Chunk Header:48,Read type:16
~~~

{: vspace="0"}
Read type: uint16
: The type of write message, which determines the layouts
of the read parameters and response payload. See later in this specification
for a list of read chunk types.

### Response

The response payload has no special layout,
and is instead defined by each write chunk type.
This data is a sequence of binary data that follows the array encoding format.

## Subscribe

The subscribe chunk allows transmitters to subscribe to a set of pre-defined data streams
on the receiver.
Once subscribed, the receiver will send stream chunks to the transmitter when it generates
data related to the subscribed data stream.
Transmitters may also unsubscribe at any point to stop receiving stream chunks.
All subscribe chunks have protobuf encoded subscribe parameters that are
defined by each subscribe type, which are defined later in this specification.

~~~ protocol
Chunk Header:48,Subscribe ID:16,S:1
~~~

{: vspace="0"}
Subscribe Type: uint16
: The stream type to operate on. This defines the layout of the subscribe parameter,
as well as the stream chunks.

S: bool
: True to subscribe, false to unsubscribe.

The subscribe parameters immediately follow these values.

### Response

~~~ protocol
Chunk Header:48,ACK Header:24,Code:16
~~~

{: vspace="0"}
Code: uint16
: A code that shows how the receiver processed the subscription.

The following codes are defined:

- 0x00: Success - Operation was successful
- 0x01: Subscribed - Attempted to subscribe when already subscribed, no action taken
- 0x02: Unsubscribed - Attempted to unsubscribed when not subscribed, no action taken
- 0x03: Bad subscribe type - Unrecognized subscribe type, no action taken
- 0x04: Invalid subscribe parameters - Subscribe parameters are ill formed, no action taken
- 0x05+: Reserved - Subscribe type specific error occurred, no action taken

## Stream

Stream chunks contain data from a subscribed stream.
These chunks are unique in the sense they are from sent from the board
to the client.
Steam messages contain a 'stream payload', which contains the data
from the stream the client subscribed to.
The layout of this data is dependent on the stream type,
which is described later in this specification.

~~~ protocol
Chunk Header:48,Subscribe ID:16
~~~

{: vspace="0"}
Subscribe Type: uint16
: The stream type of this data

The stream payload immediately follows these values.

### Response

The client MUST send an acknowledgement chunk
with a NULL payload.
This is used by the board to determine if a retransmission is necessary.

## Batch

Batch chunks allow for multiple chunks to be sent as a single packet.
They consist of a sequence of chunks that MUST be processed and executed
in the order they are defined.
This allows for clients to compress multiple operations into a single message,
which can potentially improve throughput and guarantee an ordered execution.

While batch chunks are optional, clients SHOULD make efforts to batch chunks.
In particular, they should attempt to batch a collection of small chunks,
such as control messages.
Clients SHOULD NOT batch larger messages such as data reads/writes,
but this is left to the discretion of the implementation.

Theoretically, recursive batch chunks are possible,
but clients SHOULD NOT do this as it leads to extra complexity.

TODO: Add figure showcasing batch chunk layout and repetition

### Response

The batch response is a series of ordered acknowledgement chunks
in an identical format to the batch chunk.

TODO: Again, add figure showing this layout

# Control Chunks

TODO: Define types, outline parameter/response schemes

# Data Read Chunks

TODO: Define types, outline parameter/response schemes

# Data Write Chunks

TODO: Define types, outline parameter/response schemes

# Subscribe Chunks

TODO: Define types, outline parameter/response schemes

# Stream Chunks

TODO: Define types, outline parameter/response schemes

# Security Considerations

TODO Security


# IANA Considerations

This document has no IANA actions.


--- back

# Acknowledgments
{:numbered="false"}

TODO acknowledge.
