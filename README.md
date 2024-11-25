# InstapaperGDocs
Scan Instapaper folder for GDocs and copy to new folder in date sorted order.
I made this because I have a folder where I throw bookmarks to Google Docs from several authors as I find them. But what I wanted was to see the newest Docs first and to see the authors in the title.

Fixes two Instapaper problems:
1. Bookmarks are listed in the order you added them, not by the date of the article and you can't manually reorder them when you have more than one page of bookmarks.
2. Instapaper does a terrible job of parsing Google Docs. It's better to just make a header with the title, author, date and link to the actual Google Doc

Note: There is some weirdness around Instapaper's deduping of bookmarks. If you create another set of bookmarks with the same Title and same url (or something like that) the original bookmarks disappear, in other words when you run this multiple times to new target folders it does a MOVE not a COPY. The original created bookmarks will disappear.

