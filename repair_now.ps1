$ErrorActionPreference = "Stop"

$root = "C:\Users\Grace\Desktop\SaaS\django-SaaS\NoName"

$checks = @(
    @{ Name = "Binary replace helper";       Path = "$root\SERVICE_INTERNAL\images.py"; Needle = "def replace_advert_storage_binary" },
    @{ Name = "Storage filters/totals";      Path = "$root\ADMIN\views.py"; Needle = "def _advert_storage_file_rows(reference, query" },
    @{ Name = "Storage total size";          Path = "$root\ADMIN\views.py"; Needle = "storage_total_size" },
    @{ Name = "ZIP README.md";               Path = "$root\ADMIN\views.py"; Needle = "README.md" },
    @{ Name = "ZIP ERRORS.md";               Path = "$root\ADMIN\views.py"; Needle = "ERRORS.md" },
    @{ Name = "ZIP live links";              Path = "$root\ADMIN\views.py"; Needle = "Live link" },
    @{ Name = "Media replacement";           Path = "$root\ADMIN\views.py"; Needle = "replacement = request.FILES.get" },
    @{ Name = "Upload panel";                Path = "$root\ADMIN\templates\ADMIN\partials\advert_reference_storage.html"; Needle = "data-storage-upload-form" },
    @{ Name = "Storage total UI";            Path = "$root\ADMIN\templates\ADMIN\partials\advert_reference_storage.html"; Needle = "ads-storage-total" },
    @{ Name = "Server filters";              Path = "$root\ADMIN\templates\ADMIN\partials\advert_storage_list.html"; Needle = "data-storage-q" },
    @{ Name = "Load more";                   Path = "$root\ADMIN\templates\ADMIN\partials\advert_storage_list.html"; Needle = "ads-storage-more" },
    @{ Name = "Image studio";                Path = "$root\ADMIN\templates\ADMIN\partials\advert_storage_editor.html"; Needle = "data-image-studio" },
    @{ Name = "Video studio";                Path = "$root\ADMIN\templates\ADMIN\partials\advert_storage_editor.html"; Needle = "data-video-studio" },
    @{ Name = "Replacement input";           Path = "$root\ADMIN\templates\ADMIN\partials\advert_storage_editor.html"; Needle = "data-replacement-input" },
    @{ Name = "Workspace CSS";               Path = "$root\ADMIN\static\control\css\advert_references.css"; Needle = "ads-storage-workspace" },
    @{ Name = "Upload cancel JS";            Path = "$root\ADMIN\static\control\js\advert_references.js"; Needle = "data-storage-cancel" },
    @{ Name = "Video trim JS";               Path = "$root\ADMIN\static\control\js\advert_references.js"; Needle = "applyVideoTrim" },
    @{ Name = "Cache buster";                Path = "$root\ADMIN\templates\ADMIN\advert_references.html"; Needle = "?v=20261126-1" }
)

foreach ($check in $checks) {
    if (-not (Test-Path $check.Path)) {
        throw "Missing file: $($check.Path)"
    }
    $text = [IO.File]::ReadAllText($check.Path)
    if (-not $text.Contains($check.Needle)) {
        throw "Missing marker [$($check.Name)]: $($check.Needle)"
    }
    Write-Host "OK - $($check.Name)"
}

Write-Host "All Ads storage refactor markers verified."