create extension if not exists vector;

create schema if not exists oso;

create table if not exists oso.msg (
    msg_id varchar(255) primary key,
    created_at int not null default extract(epoch from now()),
    locked_at int,
    source varchar(255) not null,
    sender varchar(255) not null,
    receiver varchar(255) not null,
    is_receiver_me bool not null,
    subject varchar(255),
    body text,
    meta jsonb not null default '{}',
    classification varchar(255),
    reply_body text,
    reply_id varchar(255),
    summary text,
    images bytea[],
    post_id varchar(255)
);

create index if not exists idx_msg_sender_created_at on oso.msg (sender, created_at desc);
