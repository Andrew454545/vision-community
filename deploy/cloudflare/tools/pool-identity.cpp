// Offline exact-panorama allocation. Hashes route records to bounded partitions;
// all identity decisions compare the complete 22-byte panorama ID.
#include <arrow/api.h>
#include <arrow/io/api.h>
#include <arrow/ipc/api.h>
#include <algorithm>
#include <array>
#include <cmath>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <limits>
#include <string>
#include <vector>
namespace fs = std::filesystem;
constexpr uint32_t INDEXED = UINT32_MAX, COMMUNITY = UINT32_MAX - 1,
                   RESERVED = UINT32_MAX - 2;
constexpr size_t PARTS = 128;
#pragma pack(push, 1)
struct Record { char pano[22]; uint32_t row; };
#pragma pack(pop)
static_assert(sizeof(Record) == 26);
void require(bool ok, const std::string &why) { if (!ok) throw std::runtime_error(why); }
bool valid_id(std::string_view p) {
  if (p.size() != 22) return false;
  for (unsigned char c : p) if (!((c >= 'A' && c <= 'Z') || (c >= 'a' && c <= 'z') ||
      (c >= '0' && c <= '9') || c == '-' || c == '_')) return false;
  return true;
}
uint64_t route(std::string_view p) {
  uint64_t h = 14695981039346656037ULL;
  for (unsigned char c : p) { h ^= c; h *= 1099511628211ULL; }
  return h;
}
std::vector<std::string> fields(const std::string &s) {
  std::vector<std::string> result; size_t at = 0;
  for (;;) { auto next = s.find('\t', at); result.push_back(s.substr(at, next - at));
    if (next == std::string::npos) return result; at = next + 1; }
}
std::string pano_from_line(const std::string &line, bool plain = false) {
  if (plain) return line;
  auto f = fields(line);
  require(f.size() == 9 || f.size() == 11 || f.size() == 12, "Unexpected pose column count");
  return f[7];
}
bool header(const std::string &line) {
  return line.starts_with("map_id\t") || line.starts_with("location_index\t");
}
struct Bits {
  uint64_t rows; std::vector<uint8_t> bytes;
  explicit Bits(uint64_t n) : rows(n), bytes((n + 7) / 8, 0) { require(n < RESERVED, "Too many source rows"); }
  void set(uint32_t row) { require(row < rows, "Source row outside sealed bounds"); bytes[row / 8] |= 1u << (row % 8); }
  bool get(uint32_t row) const { return row < rows && (bytes[row / 8] & (1u << (row % 8))); }
  void save(const fs::path &p) const { std::ofstream f(p, std::ios::binary); f.write((const char *)bytes.data(), bytes.size()); require(bool(f), "Mask write failed"); }
};
struct Partitions {
  fs::path dir; std::array<std::ofstream, PARTS> outputs;
  uint64_t records = 0, malformed = 0;
  explicit Partitions(const fs::path &d) : dir(d) {
    require(!fs::exists(d), "Output exists; preserve the earlier attempt");
    require(fs::create_directory(d), "Could not create private output");
    for (size_t i = 0; i < PARTS; ++i) outputs[i].open(d / ("part-" + std::to_string(i) + ".bin"), std::ios::binary);
  }
  void add(std::string_view p, uint32_t row) {
    if (!valid_id(p)) { ++malformed; return; }
    Record r{}; memcpy(r.pano, p.data(), 22); r.row = row;
    auto &f = outputs[route(p) % PARTS]; f.write((const char *)&r, sizeof(r));
    require(bool(f), "Partition write failed"); ++records;
  }
  void close() { for (auto &f : outputs) { f.flush(); require(bool(f), "Partition flush failed"); f.close(); } }
};
struct Counts {
  uint64_t eligible = 0, duplicates = 0, local = 0, reserved = 0, community = 0,
           distinctLocal = 0, distinctReserved = 0, distinctCommunity = 0;
};
Counts reduce(Partitions &p, Bits &bits) {
  p.close(); Counts c;
  for (size_t i = 0; i < PARTS; ++i) {
    auto path = p.dir / ("part-" + std::to_string(i) + ".bin");
    auto length = fs::file_size(path);
    require(length % sizeof(Record) == 0 && length <= 512ULL * 1024 * 1024,
            "Invalid or oversized partition; bounded-memory processing refused");
    std::vector<Record> records(length / sizeof(Record));
    std::ifstream input(path, std::ios::binary); input.read((char *)records.data(), length);
    require(length == 0 || uint64_t(input.gcount()) == length, "Incomplete partition");
    std::sort(records.begin(), records.end(), [](const auto &a, const auto &b) {
      int order = memcmp(a.pano, b.pano, 22); return order < 0 || (order == 0 && a.row < b.row);
    });
    for (size_t at = 0; at < records.size();) {
      size_t end = at + 1; while (end < records.size() && memcmp(records[at].pano, records[end].pano, 22) == 0) ++end;
      bool local = false, reserved = false, community = false; uint64_t candidates = 0;
      for (size_t j = at; j < end; ++j) {
        local |= records[j].row == INDEXED; reserved |= records[j].row == RESERVED;
        community |= records[j].row == COMMUNITY; candidates += records[j].row < RESERVED;
      }
      c.distinctLocal += local; c.distinctReserved += reserved; c.distinctCommunity += community;
      if (local) c.local += candidates;
      else if (reserved) c.reserved += candidates;
      else if (community) c.community += candidates;
      else if (candidates) { bits.set(records[at].row); ++c.eligible; c.duplicates += candidates - 1; }
      at = end;
    }
    input.close(); fs::remove(path);
    if (i % 16 == 0) std::cout << "{\"stage\":\"exact-reduction\",\"part\":" << i << ",\"eligible\":" << c.eligible << "}" << std::endl;
  }
  return c;
}
void load_spec(const fs::path &spec, Partitions &p, bool owner_mode) {
  std::ifstream config(spec); require(bool(config), "Missing owner allocation inputs");
  std::string definition;
  while (std::getline(config, definition)) {
    if (definition.empty()) continue; auto f = fields(definition);
    require(f.size() == 3, "Invalid private owner input specification");
    auto kind = f[0]; uint64_t limit = std::stoull(f[1]);
    require(kind == "indexed" || kind == "queue" || kind == "reserved" || kind == "community", "Unknown input role");
    std::ifstream input(f[2]); require(bool(input), "Missing owner input file");
    uint64_t row = 0; std::string line;
    while (std::getline(input, line)) {
      if (!line.empty() && line.back() == '\r') line.pop_back();
      if (line.empty() || header(line)) continue;
      if ((kind == "indexed" && limit && row >= limit) || (kind == "queue" && !owner_mode && row >= limit)) break;
      auto pano = pano_from_line(line, kind == "community");
      uint32_t marker = kind == "community" ? COMMUNITY : kind == "reserved" ? RESERVED : INDEXED;
      if (kind == "queue" && owner_mode && row >= limit) {
        require(row < RESERVED, "Queue is too large"); marker = uint32_t(row);
      }
      p.add(pano, marker); ++row;
    }
    require(input.eof() || !input.fail(), "Owner input read failed");
    require(!limit || row >= limit, "Owner input shorter than its recorded prefix");
    std::cout << "{\"stage\":\"owner-input\",\"kind\":\"" << kind << "\",\"rows\":" << row << "}" << std::endl;
  }
}
std::shared_ptr<arrow::ipc::RecordBatchFileReader> reader(const fs::path &path) {
  auto file = arrow::io::ReadableFile::Open(path.string()); require(file.ok(), "Cannot read source Arrow");
  auto r = arrow::ipc::RecordBatchFileReader::Open(*file); require(r.ok(), "Invalid source Arrow"); return *r;
}
void report(const fs::path &dir, const Counts &c, uint64_t rows, uint64_t malformed, uint64_t reserved = 0) {
  std::ofstream f(dir / "identity-report.json");
  f << "{\"sourceRows\":" << rows << ",\"eligibleUnique\":" << c.eligible << ",\"duplicateSourceRows\":" << c.duplicates
    << ",\"excludedLocalRows\":" << c.local << ",\"excludedReservedRows\":" << c.reserved << ",\"excludedCommunityRows\":" << c.community
    << ",\"distinctLocalIds\":" << c.distinctLocal << ",\"distinctReservedIds\":" << c.distinctReserved << ",\"distinctCommunityIds\":" << c.distinctCommunity
    << ",\"malformedInputIds\":" << malformed << ",\"localReservationRows\":" << reserved
    << ",\"identityComparison\":\"complete-22-byte-panorama-id\",\"hashesUsedOnlyForRouting\":true,\"productionQualified\":false}\n";
  require(bool(f), "Report write failed");
}
int main(int argc, char **argv) { try {
  require(argc == 6, "owner SPEC OUTPUT QUEUE_ROWS RESERVE_ROWS; source SPEC OUTPUT SOURCE_ROWS ARROW");
  std::string mode = argv[1]; fs::path spec = argv[2], out = argv[3]; uint64_t rows = std::stoull(argv[4]);
  require(mode == "owner" || mode == "source", "Unknown mode");
  require(fs::space(out.parent_path()).available > (rows + 32000000ULL) * sizeof(Record) + 1024ULL * 1024 * 1024,
          "Insufficient free disk for exact identity partitions and safety margin");
  Partitions partitions(out); Bits eligible(rows); load_spec(spec, partitions, mode == "owner");
  if (mode == "owner") {
    uint64_t requested = std::stoull(argv[5]); auto counts = reduce(partitions, eligible);
    std::ifstream defs(spec); std::string line, queue; uint64_t start = 0;
    while (std::getline(defs, line)) { auto f = fields(line); if (f.size() == 3 && f[0] == "queue") { require(queue.empty(), "Multiple local queues"); queue = f[2]; start = std::stoull(f[1]); } }
    require(!queue.empty() && counts.eligible >= requested, "Insufficient distinct unindexed local work");
    std::ifstream input(queue); std::ofstream output(out / "local-reserved.tsv"); uint64_t row = 0, written = 0;
    while (written < requested && std::getline(input, line)) {
      if (!line.empty() && line.back() == '\r') line.pop_back(); if (line.empty() || header(line)) continue;
      if (row >= start && eligible.get(row)) { output << line << '\n'; ++written; }
      ++row;
    }
    require(written == requested && bool(output), "Incomplete local reservation");
    output.close(); eligible.save(out / "unindexed-queue.bits"); report(out, counts, rows, partitions.malformed, written);
    std::ofstream boundary(out / "local-boundary.json"); boundary << "{\"startQueueRow\":" << start << ",\"exclusiveEndQueueRow\":" << row << ",\"reservedUniqueLocations\":" << written << ",\"liveQueueRewritten\":false}\n";
  } else {
    auto r = reader(argv[5]); uint64_t at = 0;
    for (int batch = 0; batch < r->num_record_batches(); ++batch) {
      auto result = r->ReadRecordBatch(batch); require(result.ok(), "Arrow batch read failed"); auto b = *result;
      require(b->GetColumnByName("pano_id") && b->GetColumnByName("pano_id")->type_id() == arrow::Type::STRING, "Unsupported panorama column");
      auto ids = std::static_pointer_cast<arrow::StringArray>(b->GetColumnByName("pano_id"));
      for (int64_t i = 0; i < b->num_rows(); ++i) {
        require(at + i < rows, "Source grew beyond snapshot");
        if (ids->IsNull(i)) ++partitions.malformed; else partitions.add(ids->GetView(i), uint32_t(at + i));
      }
      at += b->num_rows(); if (batch % 50 == 0) std::cout << "{\"stage\":\"source-partition\",\"batch\":" << batch << ",\"rows\":" << at << "}" << std::endl;
    }
    require(at == rows, "Source row count changed"); auto counts = reduce(partitions, eligible);
    eligible.save(out / "eligible.bits"); report(out, counts, rows, partitions.malformed);
  }
  return 0;
} catch (const std::exception &e) { std::cerr << e.what() << std::endl; return 1; } }
