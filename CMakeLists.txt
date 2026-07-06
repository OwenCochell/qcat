# qcat — QICK gRPC protocol definitions.
#
# This project only *generates* client/server sources from the .proto files;
# it does not compile them (that is the downstream consumer's job). Hence
# LANGUAGES NONE — no C/C++ compiler is required just to run codegen.
#
# Usage:
#   cmake -B build -DQCAT_ENABLE_CPP=ON -DQCAT_ENABLE_PYTHON=ON
#   cmake --build build
# Generated sources land under build/gen/<language>/qcat/...
#
# Toggle languages with -DQCAT_ENABLE_<LANG>=ON/OFF. Set -DQCAT_WITH_GRPC=OFF
# to emit only protobuf message types (no service stubs), which needs just
# protoc with no gRPC plugins installed.

cmake_minimum_required(VERSION 3.16)
project(qcat_proto LANGUAGES NONE)

# ---------------------------------------------------------------------------
# Options
# ---------------------------------------------------------------------------
option(QCAT_ENABLE_CPP    "Generate C++ sources"    ON)
option(QCAT_ENABLE_PYTHON "Generate Python sources" ON)
option(QCAT_ENABLE_CSHARP "Generate C# sources"     OFF)
option(QCAT_ENABLE_GO     "Generate Go sources"     OFF)
option(QCAT_WITH_GRPC     "Also generate gRPC service stubs (not just messages)" ON)
set(QCAT_GEN_DIR "${CMAKE_BINARY_DIR}/gen" CACHE PATH
    "Base output directory for generated code")

# The proto import root: imports are written as "qcat/messages/...", so the
# path passed to --proto_path must be the directory that contains qcat/.
set(QCAT_PROTO_ROOT "${CMAKE_CURRENT_SOURCE_DIR}")

# ---------------------------------------------------------------------------
# Toolchain: protoc + (optional) gRPC plugins
#
# Codegen only needs the protoc/plugin *executables*, so we locate them with
# find_program rather than find_package(protobuf/gRPC) — the latter pull in the
# C++ libraries (absl -> FindThreads) and would force a C/C++ compiler even for
# a pure Python generation. gRPC plugins from a standard install live on PATH
# (grpc_cpp_plugin, grpc_python_plugin, ...); otherwise point CMake at them with
# -DQCAT_PLUGIN_<name>=/path/to/plugin.
# ---------------------------------------------------------------------------
find_program(QCAT_PROTOC protoc REQUIRED)

# Resolve a protoc plugin executable by name into <outvar>, or "" if absent.
function(_qcat_find_plugin outvar name)
    find_program(QCAT_PLUGIN_${name} ${name})
    if(QCAT_PLUGIN_${name})
        set(${outvar} "${QCAT_PLUGIN_${name}}" PARENT_SCOPE)
    else()
        set(${outvar} "" PARENT_SCOPE)
    endif()
endfunction()

# ---------------------------------------------------------------------------
# Collect proto files (CONFIGURE_DEPENDS re-globs when files are added/removed)
# ---------------------------------------------------------------------------
file(GLOB_RECURSE QCAT_PROTOS CONFIGURE_DEPENDS "${QCAT_PROTO_ROOT}/qcat/*.proto")
if(NOT QCAT_PROTOS)
    message(FATAL_ERROR "qcat: no .proto files found under ${QCAT_PROTO_ROOT}/qcat")
endif()
list(LENGTH QCAT_PROTOS QCAT_PROTO_COUNT)

file(MAKE_DIRECTORY "${CMAKE_CURRENT_BINARY_DIR}/stamps")

# Register a codegen target: run protoc once over all protos with <flags>,
# emitting into <out_dir>. Re-runs whenever any .proto changes.
function(qcat_codegen name out_dir)
    set(flags ${ARGN})
    file(MAKE_DIRECTORY "${out_dir}")
    set(stamp "${CMAKE_CURRENT_BINARY_DIR}/stamps/${name}.stamp")
    add_custom_command(
        OUTPUT "${stamp}"
        COMMAND "${QCAT_PROTOC}"
                "--proto_path=${QCAT_PROTO_ROOT}"
                ${flags}
                ${QCAT_PROTOS}
        COMMAND "${CMAKE_COMMAND}" -E touch "${stamp}"
        DEPENDS ${QCAT_PROTOS}
        COMMENT "qcat: generating ${name} (${QCAT_PROTO_COUNT} protos) -> ${out_dir}"
        VERBATIM
    )
    add_custom_target(${name} ALL DEPENDS "${stamp}")
endfunction()

# Guard: grpc requested for a language but its plugin is missing.
function(_qcat_require_plugin lang plugin outvar)
    _qcat_find_plugin(_p ${plugin})
    if(NOT _p)
        message(FATAL_ERROR
            "qcat: QCAT_WITH_GRPC=ON but ${plugin} (needed for ${lang} gRPC stubs) "
            "was not found. Install the gRPC ${lang} plugin, or configure with "
            "-DQCAT_WITH_GRPC=OFF to emit protobuf messages only.")
    endif()
    set(${outvar} "${_p}" PARENT_SCOPE)
endfunction()

# ---------------------------------------------------------------------------
# Language targets
# ---------------------------------------------------------------------------
set(QCAT_ENABLED_LANGS "")

if(QCAT_ENABLE_CPP)
    set(_dir "${QCAT_GEN_DIR}/cpp")
    set(_flags "--cpp_out=${_dir}")
    if(QCAT_WITH_GRPC)
        _qcat_require_plugin("C++" grpc_cpp_plugin _plg)
        list(APPEND _flags "--grpc_out=${_dir}" "--plugin=protoc-gen-grpc=${_plg}")
    endif()
    qcat_codegen(qcat_cpp "${_dir}" ${_flags})
    list(APPEND QCAT_ENABLED_LANGS "cpp")
endif()

if(QCAT_ENABLE_PYTHON)
    set(_dir "${QCAT_GEN_DIR}/python")
    # --pyi_out emits type stubs alongside the *_pb2.py modules.
    set(_flags "--python_out=${_dir}" "--pyi_out=${_dir}")
    if(QCAT_WITH_GRPC)
        _qcat_require_plugin("Python" grpc_python_plugin _plg)
        list(APPEND _flags "--grpc_python_out=${_dir}"
                           "--plugin=protoc-gen-grpc_python=${_plg}")
    endif()
    qcat_codegen(qcat_python "${_dir}" ${_flags})
    list(APPEND QCAT_ENABLED_LANGS "python")
endif()

if(QCAT_ENABLE_CSHARP)
    set(_dir "${QCAT_GEN_DIR}/csharp")
    set(_flags "--csharp_out=${_dir}")
    if(QCAT_WITH_GRPC)
        _qcat_require_plugin("C#" grpc_csharp_plugin _plg)
        list(APPEND _flags "--grpc_out=${_dir}" "--plugin=protoc-gen-grpc=${_plg}")
    endif()
    qcat_codegen(qcat_csharp "${_dir}" ${_flags})
    list(APPEND QCAT_ENABLED_LANGS "csharp")
endif()

if(QCAT_ENABLE_GO)
    # Go codegen uses standalone plugins (protoc-gen-go / protoc-gen-go-grpc)
    # that must be on PATH. NOTE: it also requires a `go_package` option in each
    # .proto (or an explicit M= mapping); the current protos do not declare one,
    # so add that before enabling Go.
    set(_dir "${QCAT_GEN_DIR}/go")
    find_program(QCAT_PROTOC_GEN_GO protoc-gen-go)
    if(NOT QCAT_PROTOC_GEN_GO)
        message(FATAL_ERROR "qcat: QCAT_ENABLE_GO=ON but protoc-gen-go not found on PATH.")
    endif()
    set(_flags "--go_out=${_dir}" "--go_opt=paths=source_relative")
    if(QCAT_WITH_GRPC)
        find_program(QCAT_PROTOC_GEN_GO_GRPC protoc-gen-go-grpc)
        if(NOT QCAT_PROTOC_GEN_GO_GRPC)
            message(FATAL_ERROR "qcat: QCAT_WITH_GRPC=ON but protoc-gen-go-grpc not found on PATH.")
        endif()
        list(APPEND _flags "--go-grpc_out=${_dir}" "--go-grpc_opt=paths=source_relative")
    endif()
    qcat_codegen(qcat_go "${_dir}" ${_flags})
    list(APPEND QCAT_ENABLED_LANGS "go")
endif()

if(NOT QCAT_ENABLED_LANGS)
    message(FATAL_ERROR "qcat: no languages enabled. Set at least one -DQCAT_ENABLE_<LANG>=ON.")
endif()

message(STATUS "qcat: ${QCAT_PROTO_COUNT} protos | languages: ${QCAT_ENABLED_LANGS} | "
               "grpc stubs: ${QCAT_WITH_GRPC} | output: ${QCAT_GEN_DIR}")
