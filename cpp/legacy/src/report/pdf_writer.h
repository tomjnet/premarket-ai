// Copyright 2026 premarket-ai contributors
// SPDX-License-Identifier: MIT
//
// A tiny flowing-text PDF writer on top of libharu (US Letter, Helvetica).

#ifndef PREMARKET_AI_CPP_LEGACY_SRC_REPORT_PDF_WRITER_H_
#define PREMARKET_AI_CPP_LEGACY_SRC_REPORT_PDF_WRITER_H_

#include <hpdf.h>

#include <memory>
#include <string>

#include "common/status.h"

namespace premarket {
namespace legacy {

struct TextStyle {
  bool bold;
  float size;
  float gray;  // 0 = black, 1 = white
  float space_after;

  TextStyle(bool bold_in, float size_in, float gray_in, float space_after_in)
      : bold(bold_in),
        size(size_in),
        gray(gray_in),
        space_after(space_after_in) {}
};

class PdfWriter {
 public:
  // `footer` is printed at the bottom of every page with the page number.
  static Status Create(const std::string& footer,
                       std::unique_ptr<PdfWriter>* out);
  ~PdfWriter();

  PdfWriter(const PdfWriter&) = delete;
  PdfWriter& operator=(const PdfWriter&) = delete;

  // Wraps `text` to the page width, starting new pages as needed. '\n'
  // starts a new paragraph.
  Status Write(const std::string& text, const TextStyle& style);

  // A thin horizontal rule across the text area.
  Status Rule();

  // Writes the document to `path`.
  Status Save(const std::string& path);

 private:
  explicit PdfWriter(const std::string& footer);

  Status CheckError(const char* what);
  Status NewPage();
  Status EnsureSpace(float height);
  float TextWidth(HPDF_Font font, float size, const std::string& text) const;

  static void ErrorHandler(HPDF_STATUS error_no, HPDF_STATUS detail_no,
                           void* user_data);

  HPDF_Doc doc_;
  HPDF_Page page_;
  HPDF_Font regular_;
  HPDF_Font bold_;
  std::string footer_;
  int page_count_;
  float y_;
  HPDF_STATUS error_no_;
  HPDF_STATUS detail_no_;
};

}  // namespace legacy
}  // namespace premarket

#endif  // PREMARKET_AI_CPP_LEGACY_SRC_REPORT_PDF_WRITER_H_
