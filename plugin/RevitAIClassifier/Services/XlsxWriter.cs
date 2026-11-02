using System;
using System.Collections.Generic;
using System.IO;
using System.IO.Compression;
using System.Linq;
using System.Security;
using System.Text;

namespace RevitAIClassifier.Services
{
    /// <summary>
    /// Минимальный писатель .xlsx без сторонних библиотек: листы с таблицами,
    /// жирная шапка, закреплённая первая строка, автофильтр, числа в числовых колонках.
    /// </summary>
    public static class XlsxWriter
    {
        public class Sheet
        {
            public string Name;
            public List<string[]> Rows = new List<string[]>();   // первая строка — шапка
            public HashSet<int> NumericColumns = new HashSet<int>();
        }

        public static void Save(string path, IEnumerable<Sheet> sheets)
        {
            var list = sheets.ToList();
            if (File.Exists(path)) File.Delete(path);
            using (var fs = new FileStream(path, FileMode.CreateNew))
            using (var zip = new ZipArchive(fs, ZipArchiveMode.Create))
            {
                Put(zip, "[Content_Types].xml",
                    "<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>" +
                    "<Types xmlns=\"http://schemas.openxmlformats.org/package/2006/content-types\">" +
                    "<Default Extension=\"rels\" ContentType=\"application/vnd.openxmlformats-package.relationships+xml\"/>" +
                    "<Default Extension=\"xml\" ContentType=\"application/xml\"/>" +
                    "<Override PartName=\"/xl/workbook.xml\" ContentType=\"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml\"/>" +
                    "<Override PartName=\"/xl/styles.xml\" ContentType=\"application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml\"/>" +
                    string.Concat(list.Select((s, i) =>
                        $"<Override PartName=\"/xl/worksheets/sheet{i + 1}.xml\" ContentType=\"application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml\"/>")) +
                    "</Types>");
                Put(zip, "_rels/.rels",
                    "<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>" +
                    "<Relationships xmlns=\"http://schemas.openxmlformats.org/package/2006/relationships\">" +
                    "<Relationship Id=\"rId1\" Type=\"http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument\" Target=\"xl/workbook.xml\"/>" +
                    "</Relationships>");
                Put(zip, "xl/workbook.xml",
                    "<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>" +
                    "<workbook xmlns=\"http://schemas.openxmlformats.org/spreadsheetml/2006/main\" " +
                    "xmlns:r=\"http://schemas.openxmlformats.org/officeDocument/2006/relationships\"><sheets>" +
                    string.Concat(list.Select((s, i) =>
                        $"<sheet name=\"{Esc(SheetName(s.Name))}\" sheetId=\"{i + 1}\" r:id=\"rId{i + 1}\"/>")) +
                    "</sheets></workbook>");
                Put(zip, "xl/_rels/workbook.xml.rels",
                    "<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>" +
                    "<Relationships xmlns=\"http://schemas.openxmlformats.org/package/2006/relationships\">" +
                    string.Concat(list.Select((s, i) =>
                        $"<Relationship Id=\"rId{i + 1}\" Type=\"http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet\" Target=\"worksheets/sheet{i + 1}.xml\"/>")) +
                    $"<Relationship Id=\"rId{list.Count + 1}\" Type=\"http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles\" Target=\"styles.xml\"/>" +
                    "</Relationships>");
                Put(zip, "xl/styles.xml",
                    "<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>" +
                    "<styleSheet xmlns=\"http://schemas.openxmlformats.org/spreadsheetml/2006/main\">" +
                    "<fonts count=\"2\"><font><sz val=\"10\"/><name val=\"Arial\"/></font>" +
                    "<font><b/><sz val=\"10\"/><color rgb=\"FFFFFFFF\"/><name val=\"Arial\"/></font></fonts>" +
                    "<fills count=\"3\"><fill><patternFill patternType=\"none\"/></fill><fill><patternFill patternType=\"gray125\"/></fill>" +
                    "<fill><patternFill patternType=\"solid\"><fgColor rgb=\"FF4F6D8F\"/></patternFill></fill></fills>" +
                    "<borders count=\"1\"><border/></borders>" +
                    "<cellStyleXfs count=\"1\"><xf numFmtId=\"0\" fontId=\"0\" fillId=\"0\" borderId=\"0\"/></cellStyleXfs>" +
                    "<cellXfs count=\"2\"><xf numFmtId=\"0\" fontId=\"0\" fillId=\"0\" borderId=\"0\" xfId=\"0\"/>" +
                    "<xf numFmtId=\"0\" fontId=\"1\" fillId=\"2\" borderId=\"0\" xfId=\"0\" applyFont=\"1\" applyFill=\"1\"/></cellXfs>" +
                    "<cellStyles count=\"1\"><cellStyle name=\"Normal\" xfId=\"0\" builtinId=\"0\"/></cellStyles>" +
                    "</styleSheet>");
                for (int i = 0; i < list.Count; i++)
                    Put(zip, $"xl/worksheets/sheet{i + 1}.xml", SheetXml(list[i]));
            }
        }

        static string SheetXml(Sheet s)
        {
            int cols = s.Rows.Count == 0 ? 1 : s.Rows.Max(r => r.Length);
            var sb = new StringBuilder();
            sb.Append("<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>");
            sb.Append("<worksheet xmlns=\"http://schemas.openxmlformats.org/spreadsheetml/2006/main\">");
            sb.Append("<sheetViews><sheetView workbookViewId=\"0\"><pane ySplit=\"1\" topLeftCell=\"A2\" activePane=\"bottomLeft\" state=\"frozen\"/></sheetView></sheetViews>");
            sb.Append("<cols>");
            for (int c = 0; c < cols; c++)
            {
                int w = Math.Min(60, Math.Max(8, s.Rows.Take(300).Select(r => c < r.Length ? (r[c] ?? "").Length : 0).DefaultIfEmpty(8).Max() + 2));
                sb.Append($"<col min=\"{c + 1}\" max=\"{c + 1}\" width=\"{w}\" customWidth=\"1\"/>");
            }
            sb.Append("</cols><sheetData>");
            for (int r = 0; r < s.Rows.Count; r++)
            {
                sb.Append($"<row r=\"{r + 1}\">");
                var row = s.Rows[r];
                for (int c = 0; c < row.Length; c++)
                {
                    var v = row[c] ?? "";
                    var cellRef = Col(c) + (r + 1);
                    if (r > 0 && s.NumericColumns.Contains(c) && long.TryParse(v, out var n))
                        sb.Append($"<c r=\"{cellRef}\"><v>{n}</v></c>");
                    else
                        sb.Append($"<c r=\"{cellRef}\" t=\"inlineStr\"{(r == 0 ? " s=\"1\"" : "")}><is><t xml:space=\"preserve\">{Esc(v)}</t></is></c>");
                }
                sb.Append("</row>");
            }
            sb.Append("</sheetData>");
            if (s.Rows.Count > 1) sb.Append($"<autoFilter ref=\"A1:{Col(cols - 1)}{s.Rows.Count}\"/>");
            sb.Append("</worksheet>");
            return sb.ToString();
        }

        static string Col(int i)
        {
            var s = "";
            for (i++; i > 0; i = (i - 1) / 26) s = (char)('A' + (i - 1) % 26) + s;
            return s;
        }

        static string SheetName(string n)
        {
            foreach (var ch in new[] { ':', '\\', '/', '?', '*', '[', ']' }) n = n.Replace(ch, ' ');
            return n.Length > 31 ? n.Substring(0, 31) : n;
        }

        /// <summary>Экранирование для XML + удаление управляющих символов, которые Excel не принимает.</summary>
        static string Esc(string s)
        {
            var clean = new string((s ?? "").Where(ch => ch == '\t' || ch == '\n' || ch >= ' ').ToArray());
            return SecurityElement.Escape(clean);
        }

        static void Put(ZipArchive zip, string name, string text)
        {
            var e = zip.CreateEntry(name, CompressionLevel.Optimal);
            using (var w = new StreamWriter(e.Open(), new UTF8Encoding(false)))
                w.Write(text);
        }
    }
}
