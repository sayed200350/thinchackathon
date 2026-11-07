-- For existing evidence-enabled projects. This changes only the private file size check.
begin;
alter table claim_intake_private.documents
    drop constraint documents_content_check,
    add constraint documents_content_check check (
        octet_length(content) between 1 and
        case when media_type in ('image/jpeg', 'image/png') then 12582912 else 2097152 end
    );
commit;
