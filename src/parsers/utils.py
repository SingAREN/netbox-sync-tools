def explode_ranges(input_list):
    exploded_list = []

    for item in input_list:
        if '-' in item:
            # Split the string by the hyphen to get start and end points
            start, end = item.split('-')

            # Use range() to generate all numbers from start to end (inclusive)
            for num in range(int(start), int(end) + 1):
                exploded_list.append(str(num))
        else:
            # If it's not a range, just add the item directly
            exploded_list.append(item)

    return exploded_list
