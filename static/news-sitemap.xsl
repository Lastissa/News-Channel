<?xml version="1.0" encoding="UTF-8"?>
<xsl:stylesheet version="1.0"
                xmlns:html="http://www.w3.org/TR/REC-html40"
                xmlns:sitemap="http://www.sitemaps.org/schemas/sitemap/0.9"
                xmlns:news="http://www.google.com/schemas/sitemap-news/0.9"
                xmlns:xsl="http://www.w3.org/1999/XSL/Transform">
  <xsl:output method="html" version="1.0" encoding="UTF-8" indent="yes"/>
  <xsl:template match="/">
    <html xmlns="http://www.w3.org/1999/xhtml">
      <head>
        <title>Google News Sitemap</title>
        <meta http-equiv="Content-Type" content="text/html; charset=utf-8" />
        <style type="text/css">
          body {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
            font-size: 14px;
            color: #333;
            background: #f9f9f9;
            margin: 0;
            padding: 20px;
          }
          h1 {
            color: #1a73e8;
            font-size: 24px;
            margin-bottom: 10px;
          }
          .info {
            background: #e8f0fe;
            padding: 12px 16px;
            border-radius: 4px;
            margin-bottom: 20px;
          }
          table {
            width: 100%;
            border-collapse: collapse;
            background: #fff;
            box-shadow: 0 1px 3px rgba(0,0,0,0.1);
          }
          th {
            background: #f1f3f4;
            padding: 12px;
            text-align: left;
            font-weight: 600;
            border: 1px solid #dadce0;
          }
          td {
            padding: 10px 12px;
            border: 1px solid #dadce0;
          }
          tr:hover {
            background: #f8f9fa;
          }
          a {
            color: #1a73e8;
            text-decoration: none;
          }
          a:hover {
            text-decoration: underline;
          }
          .count {
            color: #5f6368;
            margin-bottom: 16px;
          }
        </style>
      </head>
      <body>
        <h1>Google News Sitemap</h1>
        <div class="info">
          This is a Google News Sitemap for articles published within the last 2 days.
        </div>
        <div class="count">
          Number of articles: <xsl:value-of select="count(sitemap:urlset/sitemap:url)"/>
        </div>
        <table>
          <thead>
            <tr>
              <th>Article URL</th>
              <th>Title</th>
              <th>Publication Date</th>
              <th>Publication</th>
              <th>Language</th>
            </tr>
          </thead>
          <tbody>
            <xsl:for-each select="sitemap:urlset/sitemap:url">
              <tr>
                <td>
                  <a href="{sitemap:loc}" target="_blank">
                    <xsl:value-of select="sitemap:loc"/>
                  </a>
                </td>
                <td><xsl:value-of select="news:news/news:title"/></td>
                <td><xsl:value-of select="news:news/news:publication_date"/></td>
                <td><xsl:value-of select="news:news/news:publication/news:name"/></td>
                <td><xsl:value-of select="news:news/news:publication/news:language"/></td>
              </tr>
            </xsl:for-each>
          </tbody>
        </table>
      </body>
    </html>
  </xsl:template>
</xsl:stylesheet>
