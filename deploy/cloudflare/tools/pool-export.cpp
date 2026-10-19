// Offline bounded export of a separately sealed identity mask. No cloud calls.
#include <arrow/api.h>
#include <arrow/io/api.h>
#include <arrow/ipc/api.h>
#include <charconv>
#include <cmath>
#include <cstdio>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <map>
#include <string>
#include <vector>
namespace fs = std::filesystem;
void check(bool ok, const char *why) { if (!ok) throw std::runtime_error(why); }
std::string number(double n) {
  check(std::isfinite(n), "Nonfinite source pose"); if (n == 0) return "0";
  char text[64]; auto result = std::to_chars(text, text + sizeof(text), n, std::chars_format::general, 15);
  check(result.ec == std::errc(), "Number formatting failed"); return std::string(text, result.ptr);
}
int main(int argc, char **argv) { try {
  check(argc == 7, "ARROW MASK COUNTRIES OUTPUT SOURCE_ROWS ROWS_PER_SHARD");
  uint64_t expected = std::stoull(argv[5]), per_shard = std::stoull(argv[6]);
  check(per_shard > 0 && per_shard <= 500000, "Invalid bounded shard size");
  std::ifstream masks(argv[2], std::ios::binary); check(bool(masks), "Missing sealed mask");
  std::vector<uint8_t> mask((expected + 7) / 8); masks.read((char *)mask.data(), mask.size());
  check(uint64_t(masks.gcount()) == mask.size() && masks.peek() == EOF, "Incorrect mask length");
  if (expected % 8) check((mask.back() >> (expected % 8)) == 0, "Mask has out-of-range bits");
  std::map<uint32_t, std::string> countries; std::ifstream names(argv[3]); std::string line;
  while (std::getline(names, line)) {
    auto tab = line.find('\t'); check(tab != std::string::npos, "Invalid country authority");
    auto name = line.substr(tab + 1); check(!name.empty() && name.find_first_of("\t\r\n") == std::string::npos, "Invalid country name");
    check(countries.emplace(std::stoul(line.substr(0, tab)), name).second, "Duplicate country ID");
  }
  fs::path out(argv[4]); check(!fs::exists(out) && fs::create_directory(out), "Output exists or unavailable");
  auto file = arrow::io::ReadableFile::Open(argv[1]); check(file.ok(), "Cannot open source");
  auto result = arrow::ipc::RecordBatchFileReader::Open(*file); check(result.ok(), "Invalid Arrow source"); auto reader = *result;
  std::ofstream shard; std::string filename; uint64_t source_rows = 0, written = 0, shard_rows = 0, serial = 0;
  auto close = [&]() {
    if (!shard_rows) return; shard.flush(); check(bool(shard), "Shard write failed"); shard.close();
    std::cout << "{\"file\":\"" << filename << "\",\"shard\":" << serial << ",\"rows\":" << shard_rows
              << ",\"totalRows\":" << written << "}" << std::endl;
    std::string ack; check(bool(std::getline(std::cin, ack)) && ack == "VERIFIED " + filename,
                          "Upload controller stopped; current shard retained");
    ++serial; shard_rows = 0;
  };
  for (int batch = 0; batch < reader->num_record_batches(); ++batch) {
    auto got = reader->ReadRecordBatch(batch); check(got.ok(), "Batch read failed"); auto b = *got;
    auto ids = std::dynamic_pointer_cast<arrow::UInt32Array>(b->GetColumnByName("id"));
    auto panos = std::dynamic_pointer_cast<arrow::StringArray>(b->GetColumnByName("pano_id"));
    auto tags = std::dynamic_pointer_cast<arrow::ListArray>(b->GetColumnByName("tags"));
    check(ids && panos && tags, "Unsupported source identity schema");
    auto values = std::dynamic_pointer_cast<arrow::UInt32Array>(tags->values()); check(bool(values), "Unsupported country-tag type");
    std::vector<std::shared_ptr<arrow::DoubleArray>> pose;
    for (auto field : {"lat", "lng", "heading", "pitch", "zoom"}) {
      auto a = std::dynamic_pointer_cast<arrow::DoubleArray>(b->GetColumnByName(field)); check(bool(a), "Unsupported pose field"); pose.push_back(a);
    }
    for (int64_t i = 0; i < b->num_rows(); ++i, ++source_rows) {
      check(source_rows < expected, "Source grew beyond snapshot");
      if (!(mask[source_rows / 8] & (1u << (source_rows % 8)))) continue;
      check(!panos->IsNull(i) && panos->GetView(i).size() == 22, "Unsealed panorama ID");
      check(!tags->IsNull(i) && tags->value_length(i) == 1, "Unresolved country authority");
      auto country = countries.find(values->Value(tags->value_offset(i))); check(country != countries.end(), "Country ID outside authority");
      for (const auto &a : pose) check(!a->IsNull(i), "Null pose");
      check(std::abs(pose[0]->Value(i)) <= 90 && std::abs(pose[1]->Value(i)) <= 180 &&
            std::abs(pose[3]->Value(i)) <= 90 && pose[4]->Value(i) >= 0 && pose[4]->Value(i) <= 5, "Invalid source pose");
      if (!shard_rows) {
        char name[40]; snprintf(name, sizeof(name), "shard-%06llu.tsv", (unsigned long long)serial); filename = name;
        shard.open(out / filename, std::ios::binary); check(bool(shard), "Cannot create output shard");
      }
      std::string row = "all-locations\t" + std::to_string(ids->Value(i));
      for (const auto &a : pose) row += "\t" + number(a->Value(i));
      // Obsolete positional classification is never used to invent camera or road labels.
      row += "\t" + std::string(panos->GetView(i)) + "\t" + country->second + "\tunknown\tunknown\n";
      shard.write(row.data(), row.size()); ++shard_rows; ++written;
      if (shard_rows == per_shard) close();
    }
  }
  check(source_rows == expected, "Source row count changed"); close();
  std::cout << "{\"done\":true,\"totalRows\":" << written << ",\"sourceRows\":" << source_rows << ",\"shards\":" << serial << "}" << std::endl;
  return 0;
} catch (const std::exception &e) { std::cerr << e.what() << std::endl; return 1; } }
